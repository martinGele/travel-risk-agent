# 3-minute demo script

Record with the local stack (`docker compose up -d db`, API on :8000) or the AWS URL. Before
recording: `travel-risk sync`, then `travel-risk seed-demo` (optionally with
`--slack-webhook` so Approve posts to a real Slack channel), and keep the API key handy.

## 0:00–0:25 · The problem
"When a crisis hits, a travel manager has to work out who is where, who is at risk, and contact
them, usually by hand from spreadsheets. This agent reads official US and UK government
advisories every 30 minutes, matches them against the company's trips, and drafts the
messages. A person approves anything high-risk before it's sent."

## 0:25–0:55 · Messy customer data
Show the seed output: 11 trips accepted, 3 rejected with reasons (missing email, trip already
ended, the country "Narnia"). Mention "UAE", "Kiev", different date formats. "Real customer
data is never clean, so every bad row gets a reason instead of being silently fixed."

## 0:55–1:40 · The review queue
Open `/ui`. Walk through one card:
- severity, traveller, destination, dates;
- the chips: *why* it needs review (`high level`, `regional`, `sources disagree`);
- the advisory link and the model's one-sentence reason;
- the editable message.

Point at Kampala: "The US says Level 4 for Ebola, the UK has no warning. The system flags the
disagreement rather than picking one."

## 1:40–2:10 · A crisis, live
```bash
uv run travel-risk simulate-advisory --source uk_fcdo --country FR --level 4 \
  --text "FCDO advises against all travel to France due to nationwide unrest."
```
Refresh: Lena's Paris trip appears at the top as high severity. Edit one sentence, click
**Approve and send**; show it arriving in Slack. Show the **Sent** tab with who approved it.

## 2:10–2:40 · How we know it works
Show the comparison table in the README: recall, precision, severity accuracy, cost per 100
assessments for Claude, local Qwen and the rules-only baseline. Name one mistake from the eval
report and what changed because of it (e.g. the West Bank text was hidden behind Gaza's, so
same-country items are now merged).

## 2:40–3:00 · Asking Claude
In Claude Desktop with the MCP server: "Who is affected in Lebanon this week?" Close with the
design choice: "Rules decide who could be affected, the model only judges and explains, and a
person approves anything high-risk."
