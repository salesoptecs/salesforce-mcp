# Salesforce MCP Server

A free, self-hosted **Model Context Protocol (MCP) server** that lets Claude — or any MCP client — work with your Salesforce org in plain English: run SOQL/SOSL, inspect object metadata, and (optionally) create, update, and delete records.

It's **one Python file**. It runs entirely on your machine and talks to Salesforce with **your own credentials** — nothing is sent to any third party. Read-only by default.

> Built by [SalesOptecs](https://salesoptecs.com). Prefer a guided walkthrough? See the [tool page](https://salesoptecs.com/tools/salesforce-mcp), and the deep-dive video [Claudeforce vs. a Custom MCP](https://www.youtube.com/watch?v=0wpyRvwLd7I).

## Why a custom MCP server?

Salesforce ships a hosted "Claudeforce" MCP with pre-built skills. A **custom** MCP server is the other path: it runs on **your** infrastructure, exposes exactly the tools you choose, and lets you encode **your** workflows into the AI — not a vendor's. This is that server, kept deliberately small and readable.

## What it can do

| Tool | Description |
| --- | --- |
| `sf_query` / `sf_query_all` | Run SOQL (first page, or every row paginated) |
| `sf_describe` | List every field, type, and picklist on an object |
| `sf_get_record` | Fetch a single record by ID |
| `sf_search` | SOSL search across objects |
| `sf_limits` | Check your API usage and limits |
| `sf_create` / `sf_update` / `sf_upsert` / `sf_delete` | Write records — **disabled unless you opt in** |

Ask things like *"How many open opportunities over $50k close this quarter?"*, *"What fields are on Account and which are required?"*, or *"Take this CSV and update the matching Account records."*

## Requirements

- **Python 3.10+** (`python --version`). That's it — the required libraries (`mcp`, `simple-salesforce`, `truststore`) **auto-install on first run**.
- A Salesforce user with **API access** and a **security token**. [How to get your security token →](https://salesoptecs.com/tools/salesforce-mcp/security-token)
- Any MCP client: Claude Code, Cursor, Codex, Antigravity, Claude Desktop, etc.

## Quick start

1. Download [`salesforce_mcp_server.py`](salesforce_mcp_server.py) (or clone this repo) and save it somewhere permanent.
2. Add it to your MCP client config (Claude Desktop: *Settings → Developer → Edit Config*; or the `mcp.json` used by Cursor / Claude Code / Codex):

```json
{
  "mcpServers": {
    "salesforce": {
      "command": "python",
      "args": ["C:/path/to/salesforce_mcp_server.py"],
      "env": {
        "SF_USERNAME": "you@company.com",
        "SF_PASSWORD": "your-password",
        "SF_SECURITY_TOKEN": "your-security-token",
        "SF_DOMAIN": "login",
        "SF_READONLY": "1"
      }
    }
  }
}
```

3. Restart your MCP client. On first run it installs its libraries (a few seconds), then the Salesforce tools appear.

## Configuration

| Variable | Purpose |
| --- | --- |
| `SF_USERNAME` | Salesforce login (email) |
| `SF_PASSWORD` | Salesforce password |
| `SF_SECURITY_TOKEN` | Your security token |
| `SF_DOMAIN` | `login` for production (default), `test` for a sandbox |
| `SF_READONLY` | `1`/`true` disables all create/update/delete tools |

## Security

These tools act on a **live org**. Credentials live only in your MCP client's config on your machine — never commit that file. Start with `SF_READONLY=1` and/or a sandbox (`SF_DOMAIN=test`) until you trust the workflow.

## Related

- [Tableau MCP Server](https://github.com/salesoptecs/tableau-mcp) — the same idea for your Tableau dashboards.
- [SalesOptecs](https://salesoptecs.com) — practical tools and guides for sales & revenue operations.

## License

MIT — see [LICENSE](LICENSE).
