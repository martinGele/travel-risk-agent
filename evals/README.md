# Evals

50 labelled scenarios in `scenarios.yaml`, each a trip plus an advisory with the right answer.
Labels follow `docs/SEVERITY_RUBRIC.md`: *does this advisory affect this trip, and how badly?*

```bash
uv run python -m evals.run --model heuristic          # offline baseline, instant
uv run python -m evals.run --model ollama             # local Qwen 2.5 7B (ollama serve)
uv run python -m evals.run --model claude --judge     # needs ANTHROPIC_API_KEY
uv run python -m evals.run --model claude --only uk-ukraine-kyiv,us-ps-ramallah-merged
```

Reports are written to `evals/results/<model>.md` (readable) and `.json` (every outcome).

## What a scenario runs through

The same stages as production: country cleaning (`to_iso2`) → rules (`is_candidate`) → model →
routing. A trip lost at import or stopped by the rules counts as a miss, so **recall is
end-to-end**, not just the model's.

## Mix

| Category | n | What it tests |
|---|---|---|
| `clear_hit`, `low_level` | 12 | Whole-country advice at levels 2–4 |
| `regional_inside` | 12 | City inside a restricted region (real FCDO texts) |
| `regional_outside`, `regional_exception` | 10 | City outside, or explicitly excepted ("except Luxor") |
| `regional_uncertain` | 2 | Not enough detail to tell: must answer affected |
| `rules_miss`, `dates` | 6 | Level 1, finished trips, trip ending today |
| `sources_disagree` | 2 | US and UK differ by 2+ levels |
| `tricky_text_beats_status`, `merged_advisory` | 2 | The text says more than the structured level |
| `spelling`, `country_mapping` | 2 | "Kiev", Jerusalem vs. the Palestinian Territories |
| `injection`, `level_down` | 2 | Synthetic: instructions inside advisory text; restrictions eased |

34 scenarios are affected and 16 are not. 44 reach the model; 6 are settled by the rules.

## Metrics and targets (brief §8)

- **Recall ≥ 0.95**: missing an affected traveller is the worst error. The CI gate checks this.
- **System recall**: affected *or* still routed to a person (e.g. `llm_dismissed_high`). This is
  the safety net and should be 1.0 even when model recall isn't.
- **Precision ≥ 0.85**, **severity accuracy ≥ 0.80** (on true positives).
- **Calibration**: accuracy per confidence bucket, because routing uses `confidence < 0.7`.
- **Cost per 100 assessments** and latency, for the hosted vs. self-hosted table.
- **Messages** (`--judge`): an LLM judge scores clarity (1–5) and whether the action fits the
  severity. Check 10 by hand as well; a judge is a second opinion, not ground truth.

## Honest limits

- **Labels are drafts.** One person wrote them from the 17 Nov 2026 advisory texts
  (`label_status: draft`). Have a second person check them, especially the regional cases.
- **50 is small.** With 34 positives, one miss moves recall by 3 points. Grow the set from real
  mistakes: every wrong alert in production should become a scenario.
- **Advisories change.** Scenarios use saved snapshots in `tests/fixtures/`, so results are
  reproducible but don't describe today's advice.
