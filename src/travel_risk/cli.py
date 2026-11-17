"""Operator commands. Run `uv run travel-risk --help`."""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from sqlalchemy import delete, update

from travel_risk.api.auth import hash_key, new_api_key
from travel_risk.assess.pipeline import assess_new_trips, current_advisory, load_trips
from travel_risk.config import get_settings
from travel_risk.db import get_sessionmaker
from travel_risk.ingestion.materiality import classify
from travel_risk.ingestion.service import run_trigger_1, sync_all
from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source
from travel_risk.ingestion.uk_fcdo import (
    AABE_PARTS,
    AABE_WHOLE,
    AAT_WHOLE,
    level_from_alert_status,
)
from travel_risk.llm.factory import get_model
from travel_risk.models import Advisory, Organisation, Trip
from travel_risk.trips.csv_import import import_trips, parse_csv

US_LABELS = {
    1: "Level 1: Exercise Normal Precautions", 2: "Level 2: Exercise Increased Caution",
    3: "Level 3: Reconsider Travel", 4: "Level 4: Do Not Travel",
}
UK_STATUS_FOR_LEVEL = {1: (), 2: (AABE_PARTS,), 3: (AABE_WHOLE,), 4: (AAT_WHOLE,)}


def demo_csv(today: date) -> bytes:
    """Deliberately messy, like a real customer export. Fictional people, real destinations."""
    d = lambda days: today + timedelta(days=days)  # noqa: E731
    iso = lambda days: d(days).isoformat()  # noqa: E731
    uk = lambda days: d(days).strftime("%d/%m/%Y")  # noqa: E731
    text = lambda days: d(days).strftime("%d %b %Y")  # noqa: E731
    rows = [
        "Employee Name,E-mail,Destination Country,City,Departure,Return,Slack ID",
        f"Ana Petrovska,ana.petrovska@northwind.example,Lebanon,Beirut,{iso(3)},{iso(8)},",
        f"Jonas Weber,jonas.weber@northwind.example,LB,Tyre,{iso(10)},{iso(12)},",
        f"Priya Nair,priya.nair@northwind.example,Uganda,Kampala,{uk(5)},{uk(9)},",
        f"Tom Okafor,tom.okafor@northwind.example,UAE,Dubai,{text(2)},{text(6)},",
        f"Lena Fischer,lena.fischer@northwind.example,France,Paris,{iso(14)},{iso(16)},",
        f"Marko Iliev,marko.iliev@northwind.example,Ukraine,Kiev,{iso(20)},{iso(24)},",
        f"Sara Lind,sara.lind@northwind.example,Georgia,Tbilisi,{iso(7)},{iso(11)},",
        f"Kenji Mori,kenji.mori@northwind.example,Japan,Tokyo,{iso(30)},{iso(35)},",
        f"Omar Haddad,omar.haddad@northwind.example,Palestine,Ramallah,{iso(4)},{iso(6)},",
        f"Lucia Gomez,lucia.gomez@northwind.example,Mexico,Mexico City,{iso(9)},{iso(13)},",
        # Same Beirut conference as Ana: shares one model call (MATCHING_RULES.md §5).
        f"Dan Cohen,dan.cohen@northwind.example,Lebanon,beirut ,{iso(3)},{iso(8)},",
        # Rows the importer must reject, with reasons:
        f"No Email,,France,Lyon,{iso(3)},{iso(5)},",
        f"Old Trip,old.trip@northwind.example,Spain,Madrid,{iso(-20)},{iso(-15)},",
        f"Typo Country,typo@northwind.example,Narnia,Cair Paravel,{iso(3)},{iso(5)},",
    ]
    return ("\n".join(rows) + "\n").encode()


def cmd_seed_demo(session, args) -> None:
    today = date.today()
    key = new_api_key()
    webhook = args.slack_webhook
    org = Organisation(
        name="Northwind Consulting", contact_email="travel@northwind.example",
        notify_channel="slack" if webhook else "email", slack_webhook_url=webhook,
        api_key_hash=hash_key(key),
    )
    session.add(org)
    session.flush()
    parsed = parse_csv(demo_csv(today), today, day_first=True)
    outcome = import_trips(session, org.id, parsed)
    session.commit()
    model = get_model()
    created = assess_new_trips(session, load_trips(session, [t.id for t in outcome.created]),
                               model, today)
    session.commit()
    print(f"organisation id={org.id}  ({org.name})")
    print(f"API key (shown once): {key}")
    print(f"trips imported: {len(outcome.created)}, rejected: {len(parsed.rejected)}")
    for r in parsed.rejected:
        print(f"  line {r['line']}: {r['reason']}")
    print(f"assessments created with {model.name}: {len(created)}")
    print("review page: http://localhost:8000/ui  (sign in with the key above)")


def cmd_simulate(session, args) -> None:
    """Create a synthetic new advisory version so the demo doesn't wait for a real crisis."""
    source = Source(args.source)
    iso = args.country.upper()
    prev = current_advisory(session, source, iso)
    if prev is None:
        raise SystemExit(f"no current {source} advisory for {iso}; run `travel-risk sync` first")
    level = args.level
    if source is Source.UK_FCDO:
        statuses = UK_STATUS_FOR_LEVEL[level]
        level, regional, label = level_from_alert_status(statuses)
    else:
        statuses, regional, label = (), False, US_LABELS[level]
    note = args.text or f"Simulated escalation to level {level} for a demo."
    snap = AdvisorySnapshot(
        source=source, country_iso=iso, level=level, source_level_label=label,
        regional=regional, title=f"[SIMULATED] {prev.title}",
        summary=f"SIMULATED ADVISORY (demo only, not issued by any government).\n\n{note}\n\n"
                f"{prev.summary}",
        url=prev.url, published_at=prev.published_at, source_updated_at=prev.source_updated_at,
        change_description=f"SIMULATED: {note}", alert_status=tuple(statuses),
    )
    verdict = classify(snap, prev)
    session.execute(update(Advisory).where(Advisory.source == source,
                                           Advisory.country_iso == iso).values(is_current=False))
    row = Advisory(
        source=source, country_iso=iso, version=prev.version + 1, is_current=True,
        level=snap.level, source_level_label=label, regional=regional,
        alert_status=list(statuses), title=snap.title, summary=snap.summary, url=snap.url,
        published_at=snap.published_at, source_updated_at=snap.source_updated_at,
        change_description=snap.change_description, change_kind=verdict.kind,
        triggers_assessment=verdict.triggers_assessment, content_hash=snap.content_hash,
    )
    session.add(row)
    session.commit()
    n = 0
    if verdict.triggers_assessment:
        n = run_trigger_1(session, [row], get_model(), date.today())
    print(f"{source}/{iso} v{row.version}: {verdict.kind} (level {prev.level} -> {level}); "
          f"assessments created: {n}")
    print("The next real `travel-risk sync` replaces this version with the live advisory.")


def cmd_purge(session, args) -> None:
    cutoff = date.today() - timedelta(days=get_settings().trip_retention_days)
    result = session.execute(delete(Trip).where(Trip.end_date < cutoff))
    session.commit()
    print(f"deleted {result.rowcount} trips that ended before {cutoff}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="travel-risk")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="poll both advisory feeds once and assess affected trips")

    org = sub.add_parser("create-org", help="create an organisation and print its API key")
    org.add_argument("name")
    org.add_argument("contact_email")

    seed = sub.add_parser("seed-demo", help="create a demo organisation with messy sample trips")
    seed.add_argument("--slack-webhook", help="Slack incoming-webhook URL for the demo org")

    sim = sub.add_parser("simulate-advisory", help="inject a synthetic advisory change (demo)")
    sim.add_argument("--source", choices=[s.value for s in Source], default="uk_fcdo")
    sim.add_argument("--country", required=True, help="ISO alpha-2, e.g. FR")
    sim.add_argument("--level", type=int, choices=[1, 2, 3, 4], required=True)
    sim.add_argument("--text", help="what the simulated advisory says")

    sub.add_parser("purge", help="delete trips that ended more than the retention period ago")
    sub.add_parser("send-digests", help="send each organisation's daily low-severity digest")
    sub.add_parser("mcp", help="run the read-only MCP server on stdio (needs TRA_MCP_API_KEY)")
    args = parser.parse_args()

    if args.cmd == "mcp":
        from travel_risk.mcp_server import main as mcp_main

        mcp_main()  # stdout belongs to the MCP protocol; logs go to stderr
        return

    with get_sessionmaker()() as session:
        if args.cmd == "sync":
            for result in sync_all(session, get_model()):
                print(result.model_dump_json())
        elif args.cmd == "create-org":
            key = new_api_key()
            row = Organisation(
                name=args.name, contact_email=args.contact_email, api_key_hash=hash_key(key)
            )
            session.add(row)
            session.commit()
            print(f"organisation id={row.id}\nAPI key (shown once): {key}")
        elif args.cmd == "seed-demo":
            cmd_seed_demo(session, args)
        elif args.cmd == "simulate-advisory":
            cmd_simulate(session, args)
        elif args.cmd == "purge":
            cmd_purge(session, args)
        elif args.cmd == "send-digests":
            from travel_risk.notify.digest import send_digests
            from travel_risk.notify.notifier import DefaultNotifier

            sent = send_digests(session, DefaultNotifier(), date.today())
            print(f"digests sent: {len(sent)} organisation(s), {sum(sent.values())} item(s)")


if __name__ == "__main__":
    main()
