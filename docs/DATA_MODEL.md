# Data model

Source of truth: `src/travel_risk/models.py`; migrations in `migrations/versions/`. This file explains
the fields that aren't self-explanatory and which brief gap each one closes.

```
organisations 1─* travellers 1─* trips 1─* assessments *─1 advisories
                                              │ 1
                                              ├─* reviews
                                              └─* notifications
sync_runs (standalone: one row per feed poll)
```

## advisories: one row per version

| Field | Why |
|---|---|
| `version`, `is_current` | Full history per (source, country); a partial index makes "current" lookups cheap. |
| `level` | Normalised 1–4 across both sources (`MATCHING_RULES.md` §1). |
| `source_level_label` | What the source literally said, shown to reviewers. |
| `regional`, `alert_status` | Whether stricter advice covers only part of the country; raw UK statuses. |
| `source_updated_at` / `source_edited_at` | Public change date vs. any edit (UK); drives `minor` classification. |
| `change_kind`, `triggers_assessment` | Materiality verdict, stored so the audit trail shows *why* we did or didn't alert. |
| `content_hash` | Detects real text changes vs. reissues. |

## organisations

`api_key_hash`: SHA-256 of the org's API key; the key itself is shown once at creation. Every
org-scoped route resolves the org from the key and rejects a mismatched `org_id` with 404.

## trips

`organisation_id` is denormalised (it's also reachable via traveller) so every query can filter on it
directly; tenant isolation shouldn't depend on remembering a join. `city_normalised` stores the
grouping form (`MATCHING_RULES.md` §5). Trips are deleted `trip_retention_days` (30) after `end_date`.

## assessments

| Field | Why |
|---|---|
| `group_key` | Trips sharing it got one LLM call. |
| `drafted_message` | What the agent wrote, kept even if the reviewer edits it, for evals and audit. |
| `route`, `route_reasons` | Which deterministic rules sent it to review. |
| `status` | `pending → approved / edited / rejected`, or `superseded`, `digested`, `no_action`. The API filters on this. |
| `superseded_by_id` | Points at the assessment that replaced a pending one after a newer advisory version. |
| `model`, `prompt_version`, `latency_ms`, `trace_id` | Explains any wrong alert; links to the Langfuse trace. |

## reviews / notifications

Append-only. `notifications.review_id` is null for digest items (sent without per-item approval).
`notifications.organisation_id` is denormalised for the same reason as on trips.

## sync_runs

One row per poll per source: counts and errors. This feeds a "last successful sync" health signal, so a
silently broken feed gets noticed.
