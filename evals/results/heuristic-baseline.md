# Eval report: heuristic-baseline

Run 2026-11-17 · 50 scenarios · 44 model calls · advisory snapshots from 17 Nov 2026

| Metric | Value | Target |
|---|---|---|
| Recall (affected) | 1.0 | ≥ 0.95 |
| System recall (affected or sent to review) | 1.0 | 1.0 |
| Precision | 0.773 | ≥ 0.85 |
| Severity accuracy (true positives) | 0.618 | ≥ 0.80 |
| Model errors (fail-safe to review) | 0 | 0 |
| Mean / p95 latency | 0 / 0 ms | |
| Cost per 100 assessments | $0.0 | |

Confusion: TP 34 · FP 10 · FN 0 · TN 6

## Calibration (model-stage cases)

| Confidence | n | Accuracy |
|---|---|---|
| 0.0-0.5 | 0 | None |
| 0.5-0.7 | 6 | 0.833 |
| 0.7-0.9 | 38 | 0.763 |
| 0.9-1.0 | 0 | None |

## Mistakes (23)

- **uk-ukraine-kyiv** [tricky_text_beats_status] SEVERITY: expected True/high, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-ukraine-kiev-spelling** [spelling] SEVERITY: expected True/high, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-lebanon-tyre** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advice (Advise against all travel (parts)) covers parts of the country; it is unclear whether Tyre is inside them.
- **uk-lebanon-nabatieh** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-india-srinagar** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-egypt-el-arish** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advice (Advise against all travel (parts)) covers parts of the country; it is unclear whether El Arish is inside them.
- **uk-kenya-mandera** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-thailand-pattani** [regional_inside] SEVERITY: expected True/medium, got True/low at model. UK FCDO advice for this country is Advise against all but essential travel (parts).
- **uk-mexico-tijuana** [regional_inside] SEVERITY: expected True/medium, got True/low at model. UK FCDO advice for this country is Advise against all but essential travel (parts).
- **uk-colombia-cucuta** [regional_inside] SEVERITY: expected True/medium, got True/low at model. UK FCDO advice for this country is Advise against all but essential travel (parts).
- **uk-georgia-sukhumi** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advice (Advise against all travel (parts)) covers parts of the country; it is unclear whether Sukhumi is inside them.
- **uk-mexico-mexico-city** [regional_outside] FALSE ALARM: expected False/low, got True/low at model. UK FCDO advice for this country is Advise against all but essential travel (parts).
- **uk-thailand-bangkok** [regional_outside] FALSE ALARM: expected False/low, got True/low at model. UK FCDO advice for this country is Advise against all but essential travel (parts).
- **uk-egypt-cairo** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-egypt-luxor-exception** [regional_exception] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-colombia-bogota** [regional_outside] FALSE ALARM: expected False/low, got True/low at model. UK FCDO advice for this country is Advise against all but essential travel (parts).
- **uk-kenya-nairobi** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-kenya-lamu-island-exception** [regional_exception] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-india-delhi** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advice (Advise against all travel (parts)) covers parts of the country; it is unclear whether New Delhi is inside them.
- **uk-india-jammu-exception** [regional_exception] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-georgia-tbilisi** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advice for this country is Advise against all travel (parts).
- **uk-mexico-no-city** [regional_uncertain] SEVERITY: expected True/medium, got True/low at model. UK FCDO advice (Advise against all but essential travel (parts)) covers parts of the country; it is unclear whether the destination is inside them.
- **us-ps-ramallah-merged** [merged_advisory] SEVERITY: expected True/medium, got True/high at model. US State Department advice (Level 4: Do Not Travel) covers parts of the country; it is unclear whether Ramallah is inside them.
