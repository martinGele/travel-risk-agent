# Asking Claude about travel risk (MCP server)

The MCP server lets a travel manager ask questions such as *"Who is affected in Lebanon this
week?"* from Claude Desktop or Claude Code. It acts as one organisation, identified by that
organisation's API key.

**It is read-only.** There is no tool to approve, edit or send an alert: those stay on the
review page so a person decides everything that reaches a traveller.

## Tools

| Tool | Answers |
|---|---|
| `get_affected_travellers(country?, days_ahead=14)` | Who is affected, by which source, how badly, and the alert's status |
| `get_review_queue()` | What is waiting for a decision, and why each item needs review |
| `get_current_advisories(country)` | Current US and UK advisories for a country, with an excerpt |
| `get_upcoming_trips(country?, days_ahead=30)` | Upcoming and ongoing trips |

Countries can be names or codes ("Lebanon", "LB", "UAE").

## Claude Code

```bash
claude mcp add travel-risk \
  --env TRA_MCP_API_KEY=tra_... \
  -- uv run --directory ~/code/travel-risk-agent travel-risk mcp
```

## Claude Desktop

Add this to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "travel-risk": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/YOU/code/travel-risk-agent", "travel-risk", "mcp"],
      "env": { "TRA_MCP_API_KEY": "tra_..." }
    }
  }
}
```

The server reads the same `.env` as the rest of the app, so it needs the local database running
(`docker compose up -d db`).

## Example

> **You:** Who is affected in Lebanon this week?
>
> **Claude:** *(calls `get_affected_travellers(country="Lebanon", days_ahead=7)`)* Three people:
> Ana Petrovska and Dan Cohen (Beirut, same dates) and Jonas Weber (Tyre). Both the US and UK
> advisories apply. All three alerts are still waiting for review…
