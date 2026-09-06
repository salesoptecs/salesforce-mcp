# SalesOptecs Salesforce MCP — reviewed updates (local alpha)

This release focuses on a Sales Operations job: reviewing a proposed set of CRM
changes before executing it, and knowing which records succeeded afterward.
It is not an Apex/deployment toolkit. This is the public 2.0.0-alpha.1 source
release. The npm package is not published to the registry.

## What changes

- Read-only by default, including when SF_READONLY contains an unrecognized value.
- The assistant can prepare up to 200 updates by 18-character record ID, with
  before/after values, a one-hour expiry, and an instance/user binding.
- An explicit object/field update allowlist is required.
- Execution is a separate interactive terminal command, not an MCP tool.
- Changed records are skipped. Each PATCH includes If-Unmodified-Since.
- Per-record progress is persisted locally. An uncertain write is never
  automatically retried. Pending records can resume after another review.
- CSV outcome export contains record IDs and statuses, not field values.

**Breaking change:** sf_create, sf_update, sf_upsert and sf_delete are disabled,
even with SF_READONLY=0. Creation, deletion and upsert have no approved workflow
in this alpha. Existing read/query tools remain available.

## Read-only flow investigation

Three tools help the AI client investigate "why did this happen instead of X?":

1. `sf_find_flows(sobject, after_id?)` scans up to 25 visible active Flow versions
   per call for direct object references, plus direct Apex trigger candidates.
   Follow `next_after_id` until null. Each version requires a metadata read;
   discovery can use up to 27 requests per page. Unavailable metadata is reported.
2. `sf_inspect_flow(flow_id)` reads one exact 18-character Flow version ID. It
   returns entry criteria, decisions, connectors, assignments, lookups, updates,
   formulas and other metadata, plus unexpanded subflow/action dependencies.
3. `sf_diagnose_flow(sobject, record_id, field, expected_value, flow_ids)` combines
   up to five candidate versions with current record values and recent available
   Account history. It exposes the mismatch and an investigation checklist for
   the AI client to explain, with field-reference paths back to the metadata.

Example user prompt:

> Investigate why this Account is owned by Sarah when I expected Mark. Find the
> relevant active flows, finish all discovery pages, inspect candidate versions,
> and diagnose OwnerId using Mark's actual Salesforce user ID. Explain which
> conditions and actions could account for it, cite the flow version and element,
> and distinguish confirmed facts from hypotheses. Do not change anything.

Also useful: "This Account should have met the enterprise routing criteria; why
did it take the default path?" Supply the account ID and expected field value.
Use API field names/values, not display labels; resolve a user name to its ID
first. The exact-value comparison is not an evaluation of Salesforce formulas.

These tools perform GET/query calls only, work with SF_READONLY=1, and never run
flows, create debug sessions, enable logging, activate/deploy metadata, or update
records. Existing Salesforce API and metadata permissions are required. A record
reader may not have permission to read Flow definitions; do not broaden their
permissions automatically. Metadata and record context are returned to the AI
client, so review its data-handling policy. Treat embedded descriptions and text
as untrusted content, never instructions to execute.

This is an **evidence collector for AI-assisted diagnosis**, not a Salesforce
execution simulator or a guaranteed root-cause engine. Historical causality is
always marked unproven without separate execution evidence. Current values and
the current active version may differ from those at the time of the incident.

Known boundaries:

- No automatic recursive tracing of subflows, Apex bodies, integrations, legacy
  workflow rules, or arbitrary custom-metadata routing configuration. Inspect
  identified dependencies separately. Generic variables may hide object references.
- Custom-object Apex trigger discovery by object name can miss durable-ID matches.
- Flow metadata above 250 KB is explicitly omitted, not silently clipped.
- Diagnosis fetches up to 40 referenced current-record fields. Relationship
  values, prior values, lookup outputs and runtime variables remain unknown.
- Automatic history retrieval currently supports Account only, capped at the
  latest 100 visible entries across fields. Tracking, retention and access limit
  coverage; no entries does not prove nothing changed.
- A reference to OwnerId is not proof of a write, a reachable branch, or execution.
  Check connectors, assignment targets, execution order and later writers.
- Tests use synthetic responses. Live Tooling API compatibility, metadata
  permissions and the diagnosis of a known sandbox Flow remain release gates.

API references: [Salesforce Flow Tooling API](https://developer.salesforce.com/docs/atlas.en-us.api_tooling.meta/api_tooling/tooling_api_objects_flow.htm),
[Account history](https://help.salesforce.com/s/articleView?id=sf.account_history.htm&language=en_US&type=5).

## npm installation approach

The package is a Node launcher with a bundled Python server. Node 20+ and Python
3.10+ are required. There is no TypeScript rewrite and no bundled Python binary.
`setup` explicitly creates an isolated Python environment and downloads its
dependencies; there is no dependency-downloading postinstall hook.

From this directory, build a local installable archive:

```powershell
npm.cmd pack
npm.cmd install -g ./salesoptecs-salesforce-mcp-2.0.0-alpha.1.tgz
salesoptecs-mcp setup
salesoptecs-mcp doctor
```

The package is marked private to prevent accidental registry publication. Do not
recommend an npm registry install until the package has been reviewed/published.
Dependency versions currently have bounded ranges, not a fully locked Python
dependency tree. A reproducible release lock is a follow-up release requirement.

If Python is not found, set SF_PYTHON to the full python.exe path before setup.
SF_RUNTIME_DIR optionally chooses the virtual environment directory; the default
is `.salesoptecs-mcp/runtime-v02` in your home directory. Use the same runtime
directory for setup and execution.

For MCP clients that cannot launch Windows `.cmd` shims directly, use `node` as
the command and the absolute installed `bin/cli.cjs` path as its sole argument.
`npm.cmd root -g` shows the global package directory. No launcher arguments starts
MCP over stdio. Credentials belong in the client's protected environment settings,
never command-line arguments or committed configuration.

## Configure and review

The server uses SF_USERNAME, SF_PASSWORD, SF_SECURITY_TOKEN and optional SF_DOMAIN
(`test` for sandbox, `login` by default). Start in a Salesforce sandbox with a
least-privileged integration user. Set this example allowlist in both the MCP
client's environment and the separate review terminal:

```powershell
$env:SF_UPDATE_POLICY = '{"Account":["Industry"]}'
$env:SF_STATE_DIR = 'C:\path\to\private-local-mcp-state'
$env:SF_READONLY = '1'
```

Ask the assistant to call sf_prepare_updates with the object, record IDs and
proposed field values. Preparation reads Salesforce and writes a local proposal;
it does not mutate Salesforce. Review that exact proposal in a separate terminal
with the same credentials, policy, and SF_STATE_DIR:

```powershell
$env:SF_READONLY = '0'
salesoptecs-mcp review PLAN_ID
salesoptecs-mcp status PLAN_ID
salesoptecs-mcp report PLAN_ID
```

Review prints the complete proposal and requires typing `APPLY ` followed by its
full displayed SHA-256 digest. Any other answer cancels. Piped approval is refused.
The MCP client's SF_READONLY can remain 1. Raw Python remains supported: replace
`salesoptecs-mcp` with `python path/to/salesforce_mcp_server.py` for these commands.

## Failure handling and boundaries

- `succeeded`: a 204 response was received. It does not mean Salesforce automation
  had no other side effects.
- `conflict`: a preflight comparison changed or Salesforce returned 412. Prepare
  a new proposal after inspecting the current record; this row is not retried.
- `unknown`: a mutation request failed or its result was ambiguous. Reconcile
  with Salesforce and its history before preparing any replacement. It is skipped
  on resume; it is not safe to assume no write occurred.
- `pending` in a paused job: no mutation request was sent for that row. Run review
  again before the proposal expires to resume pending rows.
- `executing`/`inflight` after a crash: locked against replay. Manually reconcile
  before preparing another proposal. This alpha has no automatic recovery/reset.

This is bounded multi-record execution using individual REST requests, not Bulk
API 2.0. Preparing reads each record; execution reads it again then PATCHes it.
Budget API calls accordingly. Salesforce validation rules, permissions, triggers
and flows still apply. Local validation covers updateability, nulls, lengths and
restricted picklists, not every Salesforce field-type or business rule.

Conditional requests use HTTP-date second precision. This is not exact subsecond
compare-and-swap, a multi-record transaction, automatic rollback, or exactly-once
execution. Salesforce-side automation can change other records.

The local SQLite store contains sensitive before/after data **without encryption**.
Keep it outside source control and cloud-synced folders. Windows permissions are
inherited; use a private directory with appropriate ACLs. The digest detects
accidental payload corruption, not malicious changes by someone who can rewrite
the database. There is no automatic retention/purge or immutable audit log yet.

A terminal prompt is a workflow safeguard, **not a strong human-approval security
boundary** if an agent has terminal or filesystem access under the same OS user.
Stronger separation needs a distinct reviewer account/service and enforced access
controls. The allowlist restricts updates, not reads. Salesforce results returned
to an AI client can be sent to that client's model provider.

## Verification and release gates

Offline tests (from repository root):

```powershell
python -m unittest discover -s packages/salesforce-mcp/test -p test_*.py -v
node --test packages/salesforce-mcp/test/cli.test.cjs
```

Before production: test against a dedicated Salesforce sandbox, including a real
412, permission/validation failures, concurrent edits, automation side effects,
and network interruption. Test installation and stdio startup on clean Windows
and macOS/Linux machines. Publishing and deployment require a separate release.

The intended differentiation is a controlled operations workflow, not a claim
that no other Salesforce MCP offers similar functionality. Installation alone
is convenience, not the product advantage.
