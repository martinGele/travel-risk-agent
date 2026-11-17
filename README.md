# Travel Risk Agent

Reads official government travel advisories (US State Department, UK FCDO), matches them against a
company's upcoming trips, uses an LLM to judge who is affected and why, drafts messages, and lets a
travel manager approve them before anything is sent.

**Core design:** rules decide who *could* be affected, the LLM only judges and explains, and a person
approves anything high-risk. The LLM can escalate a case but never suppress one.

## Status

| Week | Scope | State |
|---|---|---|
| 2 | Skeleton, schema, ingestion of both feeds, materiality, matching rules | **in progress** |
| 3 | CSV import, LLM assessment, review queue API + page | stubs (501) |
| 4 | 50-scenario evals + CI gate, AWS deploy, demo | — |
| 5 | Self-hosted model comparison, Slack + email | — |
| 6 | MCP server | — |

## Docs

- [`docs/MATCHING_RULES.md`](docs/MATCHING_RULES.md): what triggers an assessment and where it is routed
- [`docs/SEVERITY_RUBRIC.md`](docs/SEVERITY_RUBRIC.md): shared by the prompt, the eval labels and reviewers
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md): tables and why each non-obvious field exists
- [`docs/DECISIONS.md`](docs/DECISIONS.md): verified feed facts and changes from the original brief

## Run locally

```bash
docker compose up -d db
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run travel-risk sync                 # poll both feeds once (about 1 min the first time)
uv run uvicorn travel_risk.api.main:app --reload
open http://localhost:8000/docs
```

Create a customer organisation and its API key:

```bash
uv run travel-risk create-org "Acme Ltd" travel@acme.example
```

## Tests

```bash
uv run pytest            # unit tests run offline against saved feed snapshots
uv run pytest -m db      # database tests (need: docker compose up -d db)
uv run ruff check .
```

Feed snapshots in `tests/fixtures/` were captured on 17 Nov 2026. Refresh them deliberately, never
from a test run.
