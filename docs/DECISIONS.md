# Decisions log

Short records of choices that change the original brief (v2, 15 Nov 2026). Newest first.

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
