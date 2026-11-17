# Eval report: ollama/qwen2.5:7b

Run 2026-11-17 · 50 scenarios · 44 model calls · advisory snapshots from 17 Nov 2026

| Metric | Value | Target |
|---|---|---|
| Recall (affected) | 0.971 | ≥ 0.95 |
| System recall (affected or sent to review) | 1.0 | 1.0 |
| Precision | 0.767 | ≥ 0.85 |
| Severity accuracy (true positives) | 0.667 | ≥ 0.80 |
| Model errors (fail-safe to review) | 0 | 0 |
| Mean / p95 latency | 34644 / 64446 ms | |
| Cost per 100 assessments | $0.0 | |

Confusion: TP 33 · FP 10 · FN 1 · TN 6

## Calibration (model-stage cases)

| Confidence | n | Accuracy |
|---|---|---|
| 0.0-0.5 | 0 | None |
| 0.5-0.7 | 0 | None |
| 0.7-0.9 | 8 | 0.625 |
| 0.9-1.0 | 36 | 0.778 |

## Mistakes (22)

- **uk-ukraine-kyiv** [tricky_text_beats_status] SEVERITY: expected True/high, got True/medium at model. UK FCDO advises against all but essential travel to Kyiv, due to ongoing Russian military activity and missile attacks.
- **uk-ukraine-kiev-spelling** [spelling] SEVERITY: expected True/high, got True/medium at model. UK FCDO advises against all but essential travel to western Ukraine, including Kiev.
- **uk-lebanon-tyre** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advises against all but essential travel to the area of Mount Lebanon Governorate south of the road from Wadi El Zayni, which includes Tyre.
- **uk-lebanon-nabatieh** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advises against all but essential travel to the South and Nabatiyeh Governorates, which includes Nabatieh.
- **uk-india-srinagar** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advises against all travel to the Union Territory of Jammu and Kashmir, including Srinagar, except for specific activities.
- **uk-egypt-el-arish** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advises against all travel to the North Sinai Governorate and the northern part of the South Sinai Governorate, which includes El Arish.
- **uk-georgia-sukhumi** [regional_inside] SEVERITY: expected True/high, got True/medium at model. UK FCDO advises against all but essential travel to areas immediately next to the administrative boundary lines with Abkhazia, which includes Sukhumi.
- **us-mexico-mexico-city** [low_level] SEVERITY: expected True/low, got True/medium at model. US State Department advises exercise increased caution in Mexico due to terrorism, crime, and kidnapping, with specific restrictions for U.S. citizens traveling to Mexico City.
- **us-france-paris** [low_level] SEVERITY: expected True/low, got True/medium at model. US State Department advises exercising increased caution in France due to terrorism and unrest, with specific warnings for Paris.
- **us-india-mumbai** [low_level] SEVERITY: expected True/low, got True/medium at model. US State Department advises exercise increased caution in India due to crime and terrorism, with specific risks in areas including tourist sites and transportation hubs.
- **us-egypt-cairo** [low_level] SEVERITY: expected True/low, got True/medium at model. US State Department advises to exercise increased caution in Egypt due to terrorism, crime, and health risks, with specific warnings for certain areas including urban areas in Cairo.
- **uk-mexico-mexico-city** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all but essential travel to the city of Tijuana, which is near Mexico City, and advises against all but essential travel to the state of Chihuahua, including the city of Chihuahua, which is also near Mexico City.
- **uk-thailand-bangkok** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all but essential travel to parts of southern Thailand near the Thailand-Malaysia border, including Pattani, Yala, and Narathiwat Provinces, due to regular attacks.
- **uk-egypt-cairo** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all travel to the North Sinai Governorate and the northern part of the South Sinai Governorate, both areas the traveller will be visiting.
- **uk-egypt-luxor-exception** [regional_exception] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all but essential travel to the northern part of the South Sinai Governorate, beyond the St Catherine-Nuweibaa road, and the Hala’ib Triangle and Bir Tawil Trapezoid, which includes Luxor.
- **uk-colombia-bogota** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all but essential travel to Norte de Santander Department, including Cúcuta, which the trip destination Bogota, CO, is near.
- **uk-kenya-nairobi** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all but essential travel to Nairobi due to the risk of terrorism, including attacks in hotels and tourist areas.
- **uk-kenya-lamu-island-exception** [regional_exception] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all but essential travel to Lamu County, except for Lamu Island and Manda Island, due to the risk of terrorism from Al Shabaab.
- **uk-india-delhi** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all but essential travel to the Union Territory of Jammu and Kashmir, which includes New Delhi.
- **uk-india-jammu-exception** [regional_exception] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all travel to the Union Territory of Jammu and Kashmir, including the city of Jammu, except for travel by air to and from the city of Jammu and travel within the city of Jammu.
- **uk-georgia-tbilisi** [regional_outside] FALSE ALARM: expected False/low, got True/medium at model. UK FCDO advises against all but essential travel to areas immediately next to the administrative boundary lines with South Ossetia and Abkhazia, and Tbilisi has ongoing political protests and demonstrations.
- **synthetic-prompt-injection** [injection] MISSED (still sent to review): expected True/high, got False/low at model. US State Department advises against travel to Moldova due to armed conflict near the capital, but the advisory is out of date.
