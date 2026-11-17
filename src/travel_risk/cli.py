"""Operator commands: `uv run travel-risk sync`, `uv run travel-risk create-org ...`."""

from __future__ import annotations

import argparse
import logging

from travel_risk.api.auth import hash_key, new_api_key
from travel_risk.db import get_sessionmaker
from travel_risk.ingestion.service import sync_all
from travel_risk.models import Organisation


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="travel-risk")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="poll both advisory feeds once")
    org = sub.add_parser("create-org", help="create an organisation and print its API key")
    org.add_argument("name")
    org.add_argument("contact_email")
    args = parser.parse_args()

    with get_sessionmaker()() as session:
        if args.cmd == "sync":
            for result in sync_all(session):
                print(result.model_dump_json())
        elif args.cmd == "create-org":
            key = new_api_key()
            row = Organisation(
                name=args.name, contact_email=args.contact_email, api_key_hash=hash_key(key)
            )
            session.add(row)
            session.commit()
            print(f"organisation id={row.id}\nAPI key (shown once): {key}")


if __name__ == "__main__":
    main()
