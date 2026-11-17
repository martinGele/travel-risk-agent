# Travel Risk Agent

Reads official government travel advisories (US State Department, UK FCDO), matches them against a
company's upcoming trips, uses an LLM to judge who is affected and why, drafts messages, and lets a
travel manager approve them before anything is sent.

**Core design:** rules decide who *could* be affected, the LLM only judges and explains, and a person
approves anything high-risk. The LLM can escalate a case but never suppress one.

## Status

| Week | Scope | State |
|---|---|---|
| 2 | Skeleton, schema, ingestion of both feeds, materiality, matching rules | done |
| 3 | CSV import, LLM assessment, review queue API + page, Slack sending | done |
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

## Demo

```bash
uv run travel-risk sync                       # real advisories
uv run travel-risk seed-demo                  # demo org + messy CSV; prints its API key
uv run uvicorn travel_risk.api.main:app --reload
open http://localhost:8000/ui                 # sign in with the key, review the queue
uv run travel-risk simulate-advisory --source uk_fcdo --country FR --level 4 \
    --text "FCDO advises against all travel to France due to nationwide unrest."
```

`seed-demo --slack-webhook https://hooks.slack.com/...` makes Approve post to Slack.

**Model.** `TRA_MODEL_PROVIDER=heuristic` (default) runs the rules-only baseline offline.
`TRA_MODEL_PROVIDER=claude` uses Claude (`claude-opus-5-5`, structured output, effort `medium`)
and needs `ANTHROPIC_API_KEY`. Either way the model only sees advisory text, city, country and
dates; names and emails are added to the message afterwards.

## Tests

```bash
uv run pytest            # unit tests run offline against saved feed snapshots
uv run pytest -m db      # database tests (need: docker compose up -d db)
uv run ruff check .
```

Feed snapshots in `tests/fixtures/` were captured on 17 Nov 2026. Refresh them deliberately, never
from a test run.
