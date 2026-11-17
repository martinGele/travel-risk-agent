# Decisions log

Short records of choices that change the original brief (v2, 15 Nov 2026). Newest first.

## 2026-11-17: Weeks 4–6

**Bugs found while writing the eval set** (before any model was run against it):
- *The model was never told a level had dropped.* The prompt asked for "Restrictions eased:"
  on a level drop, but the input had no previous level. `AssessmentInput` now carries
  `change_kind` and `previous_level` (prompt v2).
- *The West Bank was judged against Gaza's text.* Both map to `PS`; ingestion kept only the
  stricter item. Same-country items are now merged: strictest level, both texts with headings,
  `regional = true` when the levels differ.
- *"Judge from the stricter source" double-counted.* Each trip already gets one assessment per
  source, so the stricter one alerts anyway. Each assessment now judges its own advisory; the
  other source's level is context and a routing signal (`sources_disagree`) only.

**Deployment: ECS Fargate, not App Runner.** App Runner closed to new customers on
30 April 2026. One CloudFormation stack: CloudFront (HTTPS without a domain) → ALB → one
Fargate task → RDS PostgreSQL 17.11; EventBridge API destinations call the sync, digest and
purge endpoints with the operator key. Local and CI Postgres moved from 17.12 to 17.11 so all
three environments match (RDS doesn't offer 17.12 yet).

**Sync runs in the background when scheduled.** EventBridge gives up after 5 seconds; a sync
takes 30+. `?wait=false` returns at once, and a Postgres advisory lock stops overlapping syncs.

**Digest goes to the travel manager, not travellers.** Digest items skip per-item approval, so
the only safe recipient is the manager, who forwards what matters.

**Email via SES v2**; Slack and a `log` channel otherwise. Delivery errors record the exception
class only, so addresses never land in the database or logs.

**Langfuse not added.** Every assessment already stores model, prompt version, latency and the
API request id, and eval reports keep every outcome. Langfuse would add a hosted dependency
without changing what can be explained; it's an easy later addition if a customer wants it.

**MCP server is read-only** (MCP Python SDK 2.x `MCPServer`, stdio). Four tools; no approve
or send, so "sending is not a tool" (brief §6) still holds when Claude is the client.

**Local model context window set to 16k tokens.** Ollama's default silently truncates long
FCDO pages; the model class errors if a prompt fills the window instead of judging half an
advisory.

## 2026-11-17: Week 3 choices

- **Hosted model: Claude Opus 5.5** (`claude-opus-5-5`) with JSON-schema structured output and
  effort `medium`. Server-side refusal fallback (`fallbacks: "default"`) is on, so a safety
  decline is retried on a fallback model instead of returning nothing; `assessments.model`
  records which model actually answered.
- **Heuristic baseline** (`TRA_MODEL_PROVIDER=heuristic`, the default): rules only, never says
  "not affected". It makes tests and demos work offline and is the baseline row in the eval
  table. It is deliberately blunt (almost everything is high severity): the LLM's job is to beat
  its precision without losing its recall.
- **Fail-safe:** any model error (network, refusal, truncation, invalid JSON, rubric violation)
  becomes a `pending` review item with `model_error` and confidence 0. Nothing is dropped.
- **Advisory text is fenced** in `<advisory>` tags and the system prompt says it is data.
- **Review endpoint is org-scoped:** `POST /v1/orgs/{org_id}/assessments/{id}/review` instead
  of the brief's `/v1/assessments/{id}/review`, so every route resolves the org from the key.
- **CSV import assesses in the background** (FastAPI background task); the response returns
  counts at once. Ambiguous dates like 03/04/2026 are read day-first (`TRA_CSV_DAY_FIRST`) and
  reported as warnings with line numbers.
- **Slack moved from week 5 to week 3** because the demo depends on it. Email organisations use
  a `log` channel until SES lands in week 5.
- **Demo mode:** `travel-risk simulate-advisory` writes a clearly labelled `[SIMULATED]` version;
  the next real sync replaces it (as a level change, so travellers would get an "eased" update).

## 2026-11-17: Feed facts verified against live data

Live fetches on 17 Nov 2026 (snapshots in `tests/fixtures/`) corrected the brief:

- **US feed is RSS 2.0, not Atom.** `https://travel.state.gov/_res/rss/TAsTWs.xml`, 218 items. Items
  have `<title>` "Country - Level N: Label", `<pubDate>` (date only, no separate updated date), HTML
  `<description>`, `<category domain="Threat-Level">`, and `<category domain="Country-Tag">` (FIPS).
- **Country key: use the ISO alpha-3 in the URL, not FIPS.** Each item's link ends in
  `destination.<iso3>.html` (e.g. `lbn`, `irq`). Alpha-3 → alpha-2 via `pycountry`, plus four
  overrides: `xgz` Gaza → PS, `xwb` West Bank → PS, `xks` Kosovo → XK, `xqx` Saba & Sint Eustatius → BQ.
  The FIPS tag is ambiguous (Gaza and West Bank are both `IS`), so it is kept only as a fallback field.
- **UK *does* have a structured level.** Country pages carry `details.alert_status`, a list drawn from
  `avoid_all_travel_to_whole_country`, `avoid_all_travel_to_parts`,
  `avoid_all_but_essential_travel_to_whole_country`, `avoid_all_but_essential_travel_to_parts`
  (empty = no warnings). We map it to a 1–4 level (see `MATCHING_RULES.md` §1); the LLM still reads
  text to decide whether the trip's city is inside the restricted parts.
- **UK change detection is one request.** `https://www.gov.uk/api/content/foreign-travel-advice`
  returns all 226 countries with `public_updated_at` and `change_description`. We fetch a country's
  full page only when its `public_updated_at` moved. Country pages also expose `updated_at` (moves on
  non-public edits) and `change_history`.
- **UK country key** is `details.country.slug` (e.g. `democratic-republic-of-the-congo`), mapped to
  ISO by name via `pycountry` with an explicit override table; a test asserts every slug in the index
  maps.

## 2026-11-17: Fixes adopted from the brief review

1. Matching semantics written down (advisories are states; trip candidate = not yet ended).
2. Two triggers: advisory change **and** trip import.
3. Materiality filter so reissues and minor edits don't alert.
4. Routing uses a deterministic floor; LLM confidence is only one of six reasons. The LLM can escalate
   but never suppress (`llm_dismissed_high`). `affected = false` results are kept (`no_action`).
5. Recall is measured end-to-end (import → rules → LLM), not just on the LLM step.
6. Per-organisation API keys; every query filtered by `organisation_id`.
7. Data model: `drafted_message`, `status`, `route_reasons`, `superseded_by_id` on assessments;
   `regional` and `change_kind` on advisories; a `sync_runs` table.
8. It is a **workflow**, not a free-roaming agent: the assessment step is one structured-output call
   with all context passed in. A tool-using agent arrives with the MCP server (week 6).
9. No personal data goes to the LLM; grouping by (advisory, city, dates) cuts calls.
10. Scheduling is external (EventBridge → `POST /v1/advisories/sync`), not in-process, so multiple
    API instances can't double-poll.
