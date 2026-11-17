"""Run the eval set through the real pipeline stages and score it.

    uv run python -m evals.run --model heuristic
    uv run python -m evals.run --model ollama
    uv run python -m evals.run --model claude --judge      # needs ANTHROPIC_API_KEY

Each scenario goes import -> rules -> model -> routing, exactly like production, so recall is
measured end to end (a trip lost at import or in the rules counts as a miss).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml

from travel_risk.countries import UnknownCountry, to_iso2
from travel_risk.ingestion import uk_fcdo, us_state
from travel_risk.ingestion.service import merge_snapshots
from travel_risk.ingestion.snapshot import AdvisorySnapshot, Source
from travel_risk.llm.base import AssessmentInput, ModelError, RiskModel
from travel_risk.matching.rules import Route, TripLike, is_candidate, route

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
SCENARIOS = Path(__file__).parent / "scenarios.yaml"
RESULTS = Path(__file__).parent / "results"

# USD per million tokens (input, output). Ollama and the heuristic cost nothing per call.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0),
          "claude-haiku-5-5": (0.10, 0.50)}


@dataclass
class Outcome:
    id: str
    category: str
    expected_affected: bool
    expected_severity: str
    stage: str  # import | rules | model | model_error
    affected: bool = False
    severity: str = "low"
    confidence: float | None = None
    route: str | None = None
    route_reasons: list[str] = field(default_factory=list)
    reason: str = ""
    action: str = ""
    model: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    judge: dict | None = None

    @property
    def correct(self) -> bool:
        return self.affected == self.expected_affected

    @property
    def surfaced(self) -> bool:
        """Did a human see it or did it go out? (affected, or routed to review anyway)."""
        return self.affected or self.route == Route.REVIEW


class Library:
    """Real advisory snapshots from tests/fixtures, loaded once."""

    def __init__(self) -> None:
        by_country: dict[str, list[AdvisorySnapshot]] = {}
        for s in us_state.parse_feed((FIXTURES / "us_state_feed.xml").read_bytes()):
            by_country.setdefault(s.country_iso, []).append(s)
        self.us = {iso: merge_snapshots(items) for iso, items in by_country.items()}
        self.uk: dict[str, AdvisorySnapshot] = {}
        for path in FIXTURES.glob("uk_*.json"):
            if path.name == "uk_index.json":
                continue
            snap = uk_fcdo.parse_country(json.loads(path.read_text()))
            self.uk[path.stem.removeprefix("uk_")] = snap
        self.uk_by_iso = {s.country_iso: s for s in self.uk.values()}

    def advisory(self, spec: dict) -> tuple[AdvisorySnapshot, int | None, str]:
        if "synthetic" in spec:
            s = spec["synthetic"]
            snap = AdvisorySnapshot(
                source=Source(s["source"]), country_iso=s["country"], level=s["level"],
                source_level_label=s["label"], regional=s.get("regional", False),
                title=f"[SYNTHETIC] {s['country']}", summary=s["text"].strip(),
                url="https://example.invalid/synthetic", published_at=None,
                source_updated_at=None,
            )
            return snap, s.get("previous_level"), s.get("change_kind", "new")
        if spec["from"] == "us":
            return self.us[spec["country"]], None, "new"
        return self.uk[spec["page"]], None, "new"

    def other_level(self, snap: AdvisorySnapshot) -> int | None:
        other = (self.uk_by_iso if snap.source is Source.US_STATE else self.us).get(
            snap.country_iso)
        return other.level if other else None


def run_one(sc: dict, lib: Library, model: RiskModel, today: date) -> Outcome:
    exp = sc["expected"]
    out = Outcome(sc["id"], sc["category"], exp["affected"], exp["severity"], stage="import")
    trip = sc["trip"]
    try:
        country = to_iso2(trip["country"])
    except UnknownCountry as exc:
        out.error = str(exc)
        return out
    snap, previous_level, change_kind = lib.advisory(sc["advisory"])
    t = TripLike(country, trip.get("city") or None, today + timedelta(days=trip["start"]),
                 today + timedelta(days=trip["end"]))
    if not is_candidate(t, snap.country_iso, snap.level, today):
        out.stage = "rules"
        return out

    other = sc["other_level"] if "other_level" in sc else lib.other_level(snap)
    item = AssessmentInput(
        source=snap.source, country_iso=snap.country_iso, advisory_level=snap.level,
        advisory_label=snap.source_level_label, advisory_regional=snap.regional,
        advisory_text=snap.summary, city=t.city or "", start_date=t.start_date,
        end_date=t.end_date, other_source_level=other, change_kind=change_kind,
        previous_level=previous_level,
    )
    out.stage = "model"
    try:
        result = model.assess(item)
    except ModelError as exc:
        # Same fail-safe as production: affected, sent to review.
        out.stage, out.error = "model_error", str(exc)
        out.affected, out.severity, out.confidence = True, "high", 0.0
        out.route, out.route_reasons = Route.REVIEW, ["model_error"]
        return out
    ra = result.assessment
    decision = route(ra, snap.level, snap.regional, other)
    out.affected, out.severity, out.confidence = ra.affected, ra.severity, ra.confidence
    out.reason, out.action = ra.reason, ra.action
    out.route, out.route_reasons = decision.route, list(decision.reasons)
    out.model, out.latency_ms = result.model, result.latency_ms
    out.input_tokens, out.output_tokens = result.input_tokens, result.output_tokens
    return out


def score(outcomes: list[Outcome], model_name: str) -> dict:
    tp = sum(o.affected and o.expected_affected for o in outcomes)
    fp = sum(o.affected and not o.expected_affected for o in outcomes)
    fn = sum(not o.affected and o.expected_affected for o in outcomes)
    tn = sum(not o.affected and not o.expected_affected for o in outcomes)
    positives = [o for o in outcomes if o.expected_affected]
    both = [o for o in outcomes if o.affected and o.expected_affected]
    modelled = [o for o in outcomes if o.stage == "model"]
    lat = sorted(o.latency_ms for o in modelled if o.latency_ms is not None)
    tin = sum(o.input_tokens or 0 for o in modelled)
    tout = sum(o.output_tokens or 0 for o in modelled)
    price = next((p for k, p in PRICES.items() if model_name.startswith(k)), None)
    cost = (tin * price[0] + tout * price[1]) / 1e6 if price else 0.0

    buckets = {}
    for lo, hi in [(0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]:
        inb = [o for o in modelled if o.confidence is not None and lo <= o.confidence < hi]
        buckets[f"{lo:.1f}-{min(hi, 1):.1f}"] = {
            "n": len(inb),
            "accuracy": round(sum(o.correct for o in inb) / len(inb), 3) if inb else None,
        }
    judged = [o.judge for o in outcomes if o.judge]
    return {
        "n": len(outcomes),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "system_recall": round(sum(o.surfaced for o in positives) / len(positives), 3),
        "severity_accuracy": (round(sum(o.severity == o.expected_severity for o in both)
                                    / len(both), 3) if both else None),
        "model_calls": len(modelled),
        "model_errors": sum(o.stage == "model_error" for o in outcomes),
        "latency_ms": {"mean": int(statistics.mean(lat)) if lat else None,
                       "p95": lat[int(0.95 * (len(lat) - 1))] if lat else None},
        "tokens": {"input": tin, "output": tout},
        "cost_usd": round(cost, 4),
        "cost_per_100_usd": round(cost / len(modelled) * 100, 2) if modelled and price else 0.0,
        "calibration": buckets,
        "judge": ({"n": len(judged),
                   "mean_clarity": round(statistics.mean(j["clarity"] for j in judged), 2),
                   "right_action_rate": round(sum(j["right_action"] for j in judged)
                                              / len(judged), 3)} if judged else None),
    }


def report(model_name: str, metrics: dict, outcomes: list[Outcome], today: date) -> str:
    m = metrics
    lines = [
        f"# Eval report: {model_name}", "",
        f"Run {today.isoformat()} · {m['n']} scenarios · {m['model_calls']} model calls · "
        f"advisory snapshots from 17 Nov 2026", "",
        "| Metric | Value | Target |", "|---|---|---|",
        f"| Recall (affected) | {m['recall']} | ≥ 0.95 |",
        f"| System recall (affected or sent to review) | {m['system_recall']} | 1.0 |",
        f"| Precision | {m['precision']} | ≥ 0.85 |",
        f"| Severity accuracy (true positives) | {m['severity_accuracy']} | ≥ 0.80 |",
        f"| Model errors (fail-safe to review) | {m['model_errors']} | 0 |",
        f"| Mean / p95 latency | {m['latency_ms']['mean']} / {m['latency_ms']['p95']} ms | |",
        f"| Cost per 100 assessments | ${m['cost_per_100_usd']} | |",
    ]
    if m["judge"]:
        lines.append(f"| Message clarity (judge, 1–5) | {m['judge']['mean_clarity']} | |")
        lines.append(f"| Right action (judge) | {m['judge']['right_action_rate']} | |")
    c = m["confusion"]
    lines += ["", f"Confusion: TP {c['tp']} · FP {c['fp']} · FN {c['fn']} · TN {c['tn']}", "",
              "## Calibration (model-stage cases)", "", "| Confidence | n | Accuracy |",
              "|---|---|---|"]
    lines += [f"| {k} | {v['n']} | {v['accuracy']} |" for k, v in m["calibration"].items()]
    wrong = [o for o in outcomes
             if not o.correct or (o.correct and o.affected and o.severity != o.expected_severity)]
    lines += ["", f"## Mistakes ({len(wrong)})", ""]
    if not wrong:
        lines.append("None.")
    for o in wrong:
        kind = ("MISSED" if o.expected_affected and not o.affected else
                "FALSE ALARM" if o.affected and not o.expected_affected else "SEVERITY")
        surfaced = " (still sent to review)" if kind == "MISSED" and o.surfaced else ""
        lines.append(f"- **{o.id}** [{o.category}] {kind}{surfaced}: expected "
                     f"{o.expected_affected}/{o.expected_severity}, got {o.affected}/{o.severity}"
                     f" at {o.stage}. {o.reason or o.error or ''}".rstrip())
    return "\n".join(lines) + "\n"


def get_model(name: str) -> RiskModel:
    if name == "heuristic":
        from travel_risk.llm.heuristic import HeuristicRiskModel
        return HeuristicRiskModel()
    if name == "ollama":
        from travel_risk.llm.ollama import OllamaRiskModel
        return OllamaRiskModel()
    if name.startswith("claude"):
        import anthropic

        from travel_risk.llm.claude import ClaudeRiskModel
        from travel_risk.llm.factory import get_settings

        s = get_settings()
        key = s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        model_id = s.claude_model if name == "claude" else name
        return ClaudeRiskModel(model=model_id, effort=s.claude_effort, client=client)
    raise SystemExit(f"unknown model {name!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.run")
    ap.add_argument("--model", default="heuristic",
                    help="heuristic | ollama | claude | a Claude model id")
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--min-recall", type=float, default=None,
                    help="exit 1 if recall is below this (CI gate)")
    ap.add_argument("--judge", action="store_true", help="score drafted messages with Claude")
    ap.add_argument("--no-write", action="store_true", help="don't write evals/results files")
    args = ap.parse_args(argv)

    scenarios = yaml.safe_load(SCENARIOS.read_text())
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]
    lib, model, today = Library(), get_model(args.model), date.today()
    workers = args.workers or (1 if args.model in ("heuristic", "ollama") else 4)

    started = time.monotonic()
    with ThreadPoolExecutor(workers) as pool:
        outcomes = list(pool.map(lambda sc: run_one(sc, lib, model, today), scenarios))
    if args.judge:
        from evals.judge import judge_all
        judge_all(outcomes, scenarios, lib)
    metrics = score(outcomes, model.name)
    metrics["wall_seconds"] = round(time.monotonic() - started, 1)
    md = report(model.name, metrics, outcomes, today)
    print(md)

    if not args.no_write and not args.only:
        RESULTS.mkdir(exist_ok=True)
        slug = model.name.replace("/", "-").replace(":", "-")
        (RESULTS / f"{slug}.md").write_text(md)
        (RESULTS / f"{slug}.json").write_text(json.dumps(
            {"model": model.name, "date": today.isoformat(), "metrics": metrics,
             "outcomes": [asdict(o) for o in outcomes]}, indent=2, default=str))

    if args.min_recall is not None and (metrics["recall"] or 0) < args.min_recall:
        print(f"FAIL: recall {metrics['recall']} < {args.min_recall}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
