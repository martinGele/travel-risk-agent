# Severity rubric

Used by three things that must agree: the LLM prompt, the human labeller writing eval scenarios, and
the review page. Change it here first; then bump `PROMPT_VERSION` and re-label anything affected.

Severity describes **this traveller's trip**, not the country in general, and is judged from
**this advisory alone**. Each trip gets one assessment per source, so the stricter source always
produces its own alert; the other source's level is context (mention a disagreement in `reason`)
and a routing signal (`sources_disagree`), never a reason to change `affected` or `severity`.

## `affected`

`true` if the advisory gives this traveller a reason to change behaviour *for this trip*: go/don't go,
avoid an area they will be in, take a specific precaution, or leave.

`false` if the advisory applies only to places the trip does not touch (e.g. a southern border region when
the trip is a city hundreds of km away), or contains nothing beyond normal precautions.

When the trip's location relative to a restricted area is **uncertain**, answer `true` with confidence
below 0.7. Missing an affected traveller is the worst error.

## Severity

| Severity | Meaning | Typical triggers | Expected action |
|---|---|---|---|
| **high** | Travel should not happen or the traveller should leave | US Level 4 for the trip's location; FCDO "against all travel" covering the trip's city; active conflict, coup, airport closure | "Do not travel" / "Leave now" / "Contact security team immediately" |
| **medium** | Travel can happen only with changed plans or real precautions | US Level 3; FCDO "all but essential travel" covering the trip; specific threats (kidnapping, unrest) in the trip's city | Postpone non-essential travel, avoid named areas, register with the embassy, check in daily |
| **low** | Awareness only; plans stand | US Level 2; regional advice that does not cover the trip's city but is nearby; new info on protests, scams, health | Read the advisory, avoid demonstrations, keep documents ready |

Tie-breakers:
- If the two sources disagree, still judge from this advisory, and say so in `reason`.
- `affected = false` always pairs with `severity = low`.
- A level going **down** is `low` severity, `affected = true`, action "Restrictions eased: …".

## `reason` and `action`

- `reason`: one sentence that names the source and quotes or paraphrases the specific advisory line.
  Good: "FCDO advises against all travel to southern Beirut suburbs including Haret Hraik, where the
  hotel is." Bad: "Lebanon is dangerous."
- `action`: an imperative instruction a traveller can follow in 30 seconds. No raw advisory text.

## `confidence`

The model's probability that `affected` is correct. Calibration is measured in evals (reliability per
bucket), and routing never relies on confidence alone (see `MATCHING_RULES.md` §6).
