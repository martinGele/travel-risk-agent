# Matching rules

This is the contract for the code that decides **which trips are candidates for an assessment** and
**where each assessment goes**. Rules are deterministic and run before any LLM call. The LLM may make
a case *more* cautious; it can never make one disappear.

Implemented in `src/travel_risk/matching/rules.py` and `src/travel_risk/ingestion/materiality.py`.
Every rule below has a test in `tests/test_rules.py` or `tests/test_materiality.py`.

## 1. Normalised level (1–4)

Both sources are mapped onto one scale so they can be compared.

| Level | US State Dept | UK FCDO `alert_status` |
|---|---|---|
| 1 | Level 1: Exercise Normal Precautions | `[]` (no warnings) |
| 2 | Level 2: Exercise Increased Caution | `avoid_all_but_essential_travel_to_parts` |
| 3 | Level 3: Reconsider Travel | `avoid_all_travel_to_parts` **or** `avoid_all_but_essential_travel_to_whole_country` |
| 4 | Level 4: Do Not Travel | `avoid_all_travel_to_whole_country` |

If several UK statuses are present, the highest wins.

**Regional flag.** `regional = true` when the advice is stricter for part of the country than for the
whole:
- UK: any `*_to_parts` status without the matching `*_whole_country` status.
- US: level < 4 and the summary contains "Do Not Travel to" or "Level 4" (a stricter area inside a
  milder country). This is a heuristic; the LLM decides whether the trip's city is inside the area.

## 2. Advisories are states, not events

Advisories have no end date. An advisory version is **in force from the moment we ingest it until a
newer version of the same (source, country) replaces it.** So "date overlap" means:

> a trip is a candidate if `trip.end_date >= today` (the trip has not finished).

Trips that ended before the advisory was ingested are never candidates. A trip that ends today *is* a
candidate (the traveller may still be there).

## 3. Materiality: which ingested versions trigger assessments

Every fetched version is stored (one row per version). Only **material** changes trigger
assessments.

| Change kind | Definition | Triggers assessments? |
|---|---|---|
| `new` | First version we have for (source, country) | Yes, if level ≥ 2 |
| `level_up` | Normalised level increased | Yes |
| `level_down` | Normalised level decreased | Yes (travellers should hear good news too; goes to digest) |
| `scope_change` | Same level, but regional flag or UK `alert_status` set changed | Yes |
| `content_change` | Same level and scope, text hash changed, and (UK) `public_updated_at` moved | Yes, if level ≥ 2 |
| `minor` | UK: only `updated_at` moved (FCDO's own signal for non-public edits). US: hash unchanged, date moved (reissued with no changes) | **No** (stored only) |

Level 1 content changes never trigger: normal precautions do not warrant contacting anyone.

## 4. The two triggers

1. **Advisory changed.** A material version for country C → assess every candidate trip in C, across all
   organisations, against that version.
2. **Trip imported.** A new or changed trip to country C → assess it against the *current* version from
   each source for C, where that version's level ≥ 2.

## 5. Grouping (one LLM call per group, not per trip)

Candidate trips are grouped by `(advisory_id, country_iso, normalised city, start_date, end_date)`.
Twenty people at the same Beirut conference produce one LLM call. The group's assessment is copied to
each trip's `assessments` row with the same `group_key`.

The LLM receives only: advisory text, city, country, dates. **No names, emails or organisation.**
Names are filled into the drafted message by a template afterwards.

## 6. Routing (deterministic floor + LLM output)

After the LLM returns a `RiskAssessment`, the router computes `route_reasons`. The assessment goes to
**review** if *any* reason fires:

| Reason | Condition |
|---|---|
| `high_level` | advisory level ≥ 3 |
| `regional` | advisory is regional (the LLM's location call needs a human check) |
| `sources_disagree` | the other source's current level for this country differs by ≥ 2 |
| `llm_dismissed_high` | `affected = false` and advisory level ≥ 3 |
| `high_severity` | LLM severity = `high` |
| `low_confidence` | LLM confidence < 0.7 |

Otherwise:
- `affected = true` → **digest** (daily summary to the manager, sent without per-item approval).
- `affected = false` → **no_action**: stored and visible in the review page's "dismissed" tab, never
  silently dropped.

## 7. Supersession and de-duplication

- When a material version arrives for (source, country), every **pending** assessment that used an
  older version of that (source, country) becomes `superseded` and points at its replacement.
- Approved or sent assessments are never changed (they are the audit trail).
- A traveller is not sent a second message for the same (trip, source, country) unless the level went
  **up** or the scope changed since the last sent message.
- When both sources produce assessments for one trip, they are reviewed side by side, and the manager
  may send one merged message.

## 8. Known edge cases (seed the eval set from these)

- Gaza and the West Bank: US publishes them separately (mapped to `PS`); UK publishes `palestine`. A
  trip to Jerusalem (`IL`) does not match `PS`. Flag it in evals.
- US "Saba and Sint Eustatius" (`xqx`) and "Bonaire" (`bes`) both map to `BQ`; likewise Gaza and the
  West Bank both map to `PS`. Ingestion keeps the **strictest** item per country (Gaza's Level 4 wins),
  so a West Bank trip is assessed against Gaza's text. The LLM must read the regional nuance; add an
  eval case for it.
- A city spelled two ways ("Kyiv"/"Kiev") must normalise to one group key.
- A trip ending today is a candidate; a trip that ended yesterday is not.
- The US and UK sources disagree by ≥ 2 levels → always reviewed.
