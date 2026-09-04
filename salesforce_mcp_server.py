"""
Salesforce MCP Server
=====================
A Model Context Protocol (MCP) server that lets an AI assistant (Claude Desktop,
Cursor, etc.) work with your Salesforce org in natural language — run SOQL/SOSL,
inspect object metadata, and (optionally) create/update/delete records.

PREREQUISITES
-------------
1. Python 3.10+ installed and on your PATH  (check: `python --version`)
2. A Salesforce edition/user with API access enabled (Enterprise/Unlimited, or an
   org with the API add-on) and a security token for that user.
3. An MCP client to launch this file (e.g. Claude Desktop or Cursor).

The required Python libraries are installed automatically on first run (see
_ensure_deps below) — you just need Python itself.

CREDENTIALS — set these as environment variables (never hardcode them):
    SF_USERNAME          your Salesforce login (email)
    SF_PASSWORD          your Salesforce password
    SF_SECURITY_TOKEN    your Salesforce security token
    SF_DOMAIN            (optional) "login" for production [default], "test" for a sandbox
    SF_READONLY          (optional) set to "1"/"true" to DISABLE all write/delete tools

Example MCP client config (Claude Desktop / Cursor `mcpServers` entry):
    {
      "salesforce": {
        "command": "python",
        "args": ["C:/path/to/salesforce_mcp_server.py"],
        "env": {
          "SF_USERNAME": "you@company.com",
          "SF_PASSWORD": "••••••",
          "SF_SECURITY_TOKEN": "••••••",
          "SF_READONLY": "1"
        }
      }
    }

SECURITY NOTE: these tools act on a LIVE org. Start with SF_READONLY=1 and/or a
sandbox (SF_DOMAIN=test) until you trust the workflow — sf_delete/sf_update change
real data.
"""

import asyncio
import json
import os
import subprocess
import sys


def _ensure_deps() -> None:
    """Auto-install the required libraries on first run so the user only needs Python.
    All pip output goes to stderr so it can't corrupt the MCP stdio protocol on stdout."""
    for module, package in (("mcp", "mcp"), ("simple_salesforce", "simple-salesforce"), ("truststore", "truststore")):
        try:
            __import__(module)
        except ImportError:
            print(f"[setup] installing {package} (first-run only) ...", file=sys.stderr, flush=True)
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", package],
                               check=True, stdout=sys.stderr, stderr=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"[setup] could not install {package}: {exc}\n"
                      f"        Install it manually: {sys.executable} -m pip install {package}",
                      file=sys.stderr, flush=True)
                raise


_ensure_deps()

import truststore  # noqa: E402
truststore.inject_into_ssl()

from mcp.server import Server  # noqa: E402
from mcp.types import Tool, TextContent  # noqa: E402
import mcp.server.stdio  # noqa: E402
from simple_salesforce import Salesforce  # noqa: E402

# ---- configuration -------------------------------------------------------------

READONLY = os.environ.get("SF_READONLY", "").strip().lower() in ("1", "true", "yes", "on")
WRITE_TOOLS = {"sf_create", "sf_update", "sf_upsert", "sf_delete"}

app = Server("salesforce-mcp-server")
_sf = None  # cached connection


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. Set SF_USERNAME, SF_PASSWORD and "
            f"SF_SECURITY_TOKEN (and optionally SF_DOMAIN=test for a sandbox) in your MCP client config."
        )
    return value


def get_sf() -> "Salesforce":
    """Get or create the Salesforce connection from environment variables."""
    global _sf
    if _sf is None:
        _sf = Salesforce(
            username=_require_env("SF_USERNAME"),
            password=_require_env("SF_PASSWORD"),
            security_token=_require_env("SF_SECURITY_TOKEN"),
            domain=os.environ.get("SF_DOMAIN", "login"),
        )
    return _sf


def _run_with_reauth(op):
    """Run op(sf); if the session has expired, re-authenticate once and retry."""
    global _sf
    try:
        return op(get_sf())
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).upper()
        if "EXPIRED" in msg or "INVALID_SESSION" in msg or "SESSION" in msg:
            _sf = None
            return op(get_sf())
        raise


def _strip_attrs(records):
    """Drop Salesforce's per-record `attributes` metadata."""
    return [{k: v for k, v in rec.items() if k != "attributes"} for rec in records]


# ---- tools ---------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[Tool]:
    tools = [
        Tool(
            name="sf_query",
            description="Execute a SOQL query and return the first page of results as JSON (use sf_query_all for every row).",
            inputSchema={"type": "object", "properties": {
                "query": {"type": "string", "description": "SOQL query to execute"}}, "required": ["query"]},
        ),
        Tool(
            name="sf_query_all",
            description="Execute a SOQL query and return ALL rows (paginated), including deleted/archived.",
            inputSchema={"type": "object", "properties": {
                "query": {"type": "string", "description": "SOQL query to execute"}}, "required": ["query"]},
        ),
        Tool(
            name="sf_describe",
            description="Describe a Salesforce object to see all fields, types, and metadata.",
            inputSchema={"type": "object", "properties": {
                "sobject": {"type": "string", "description": "Salesforce object name (e.g., Account, Contact)"}},
                "required": ["sobject"]},
        ),
        Tool(
            name="sf_get_record",
            description="Get a single Salesforce record by ID.",
            inputSchema={"type": "object", "properties": {
                "sobject": {"type": "string", "description": "Salesforce object name"},
                "record_id": {"type": "string", "description": "Salesforce record ID"}},
                "required": ["sobject", "record_id"]},
        ),
        Tool(
            name="sf_search",
            description="Execute a SOSL search query.",
            inputSchema={"type": "object", "properties": {
                "search": {"type": "string", "description": "SOSL search string"}}, "required": ["search"]},
        ),
        Tool(
            name="sf_limits",
            description="Get current Salesforce API usage and limits.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]
    write_tools = [
        Tool(
            name="sf_create",
            description="Create a new Salesforce record.",
            inputSchema={"type": "object", "properties": {
                "sobject": {"type": "string", "description": "Salesforce object name"},
                "data": {"type": "object", "description": "Field values for the new record"}},
                "required": ["sobject", "data"]},
        ),
        Tool(
            name="sf_update",
            description="Update an existing Salesforce record.",
            inputSchema={"type": "object", "properties": {
                "sobject": {"type": "string", "description": "Salesforce object name"},
                "record_id": {"type": "string", "description": "Salesforce record ID"},
                "data": {"type": "object", "description": "Field values to update"}},
                "required": ["sobject", "record_id", "data"]},
        ),
        Tool(
            name="sf_upsert",
            description="Upsert (insert or update) a Salesforce record using an external ID.",
            inputSchema={"type": "object", "properties": {
                "sobject": {"type": "string", "description": "Salesforce object name"},
                "external_id_field": {"type": "string", "description": "External ID field name"},
                "external_id_value": {"type": "string", "description": "External ID value"},
                "data": {"type": "object", "description": "Field values for the record"}},
                "required": ["sobject", "external_id_field", "external_id_value", "data"]},
        ),
        Tool(
            name="sf_delete",
            description="Delete a Salesforce record (permanent).",
            inputSchema={"type": "object", "properties": {
                "sobject": {"type": "string", "description": "Salesforce object name"},
                "record_id": {"type": "string", "description": "Salesforce record ID to delete"}},
                "required": ["sobject", "record_id"]},
        ),
    ]
    # only advertise write/delete tools when NOT in read-only mode
    return tools if READONLY else tools + write_tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # guardrail: refuse writes in read-only mode even if a client calls them directly
    if READONLY and name in WRITE_TOOLS:
        return [TextContent(type="text", text=f"Refused: '{name}' is disabled because SF_READONLY is set.")]

    def op(sf):
        if name == "sf_query":
            result = sf.query(arguments["query"])
            records = _strip_attrs(result.get("records", []))
            total = result.get("totalSize", len(records))
            truncated = not result.get("done", True)
            note = f" (first {len(records)} of {total}; call sf_query_all for the rest)" if truncated else ""
            return [TextContent(type="text",
                    text=f"Query returned {len(records)} of {total} rows{note}:\n"
                         f"{json.dumps(records, indent=2, default=str)}")]

        if name == "sf_query_all":
            result = sf.query_all(arguments["query"])
            records = _strip_attrs(result.get("records", []))
            return [TextContent(type="text",
                    text=f"Query returned {len(records)} rows:\n{json.dumps(records, indent=2, default=str)}")]

        if name == "sf_describe":
            description = getattr(sf, arguments["sobject"]).describe()
            fields = [{
                "name": f.get("name"), "type": f.get("type"), "label": f.get("label"),
                "required": not f.get("nillable"), "createable": f.get("createable"),
                "updateable": f.get("updateable"), "length": f.get("length"),
                "picklistValues": [v["value"] for v in f.get("picklistValues", [])] or None,
            } for f in description.get("fields", [])]
            return [TextContent(type="text", text=json.dumps({
                "name": description.get("name"), "label": description.get("label"),
                "createable": description.get("createable"), "updateable": description.get("updateable"),
                "deletable": description.get("deletable"), "queryable": description.get("queryable"),
                "fields": fields,
            }, indent=2, default=str))]

        if name == "sf_get_record":
            rec = getattr(sf, arguments["sobject"]).get(arguments["record_id"])
            clean = {k: v for k, v in rec.items() if k != "attributes"}
            return [TextContent(type="text", text=json.dumps(clean, indent=2, default=str))]

        if name == "sf_search":
            result = sf.search(arguments["search"])
            records = _strip_attrs(result.get("searchRecords", []))
            return [TextContent(type="text",
                    text=f"Search returned {len(records)} rows:\n{json.dumps(records, indent=2, default=str)}")]

        if name == "sf_limits":
            return [TextContent(type="text", text=json.dumps(sf.limits(), indent=2, default=str))]

        if name == "sf_create":
            result = getattr(sf, arguments["sobject"]).create(arguments["data"])
            return [TextContent(type="text", text=f"Record created:\n{json.dumps(result, indent=2, default=str)}")]

        if name == "sf_update":
            result = getattr(sf, arguments["sobject"]).update(arguments["record_id"], arguments["data"])
            return [TextContent(type="text", text=f"Record updated (HTTP {result}).")]

        if name == "sf_upsert":
            result = getattr(sf, arguments["sobject"]).upsert(
                f"{arguments['external_id_field']}/{arguments['external_id_value']}", arguments["data"])
            return [TextContent(type="text", text=f"Record upserted (HTTP {result}).")]

        if name == "sf_delete":
            result = getattr(sf, arguments["sobject"]).delete(arguments["record_id"])
            return [TextContent(type="text", text=f"Record deleted (HTTP {result}).")]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    try:
        return _run_with_reauth(op)
    except Exception as exc:  # noqa: BLE001
        import traceback
        return [TextContent(type="text", text=f"Error: {exc}\n\nDetails:\n{traceback.format_exc()}")]


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
