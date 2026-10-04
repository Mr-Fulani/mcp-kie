# Phase 1 — Stage B: Codex stdio acceptance

Date: 2026-10-03. Result: **PASS** for Codex CLI 0.160.0 using the
installed user configuration and the project's real Keychain launcher.

## Committed baseline

Commit: `e3ce4e6fab8c766d634d798dd3ca617960f9bfcc`
(`feat: secure KIE media MCP and record Phase 1 preflight`).
The previously verified 73-test implementation was committed without rewriting
application code. The working tree was clean after that commit. No push was made.

## Owner configuration change

The following exact addition was shown before it was applied to
`/LOCAL_OWNER/.codex/config.toml`:

```diff
@@ -194,0 +195,3 @@
+[mcp_servers.kie-media]
+command = "/LOCAL_OWNER/mcp-kie/.venv/bin/kie-mcp-launch"
+args = []
```

Both the config and its private backup have mode `0600`. Backup:
`/LOCAL_OWNER/.codex/config.toml.kie-backup-private_id_11856a6924c7`.
The backup matches the original bytes. Parsing the updated config and removing
only the new entry reproduces the original settings, including providers,
profiles and defaults. No credential or environment value was added to the
Codex config. Claude Code and Grok Build configurations were not changed.

## Verified behavior

| Check | Evidence | Result |
| --- | --- | --- |
| Real launcher initializes over stdio | MCP protocol `2025-11-25`, server `Secure KIE media` | PASS |
| Expected tool inventory | All 22 existing tools, descriptions and object input schemas | PASS |
| Codex reads the installed registration | `codex mcp get kie-media --json`: enabled, stdio, expected command | PASS |
| Codex receives the tool catalog | Native app-server `mcpServerStatus/list`, no `toolsError` | PASS |
| Working project session connects | Ephemeral `thread/start`, runtime status `connected`, all 22 tools | PASS |
| MCP opens no HTTP port | `lsof` found zero listening TCP sockets in the running MCP process | PASS |
| Diagnostic Codex transport | App-server used stdio; no listening TCP sockets | PASS |
| Startup/output secret hygiene | Actual media/chat keys compared in memory with captured stdout/stderr; zero matches | PASS |

Only protocol initialization, tool/resource discovery and the local overview
resource were used. No KIE live tool was called, no model turn was started,
no budget reservation was made and no billable generation was submitted.
The standalone launcher check left the production ledger uncreated.

The native session check scanned 15,670 stdout bytes and zero stderr bytes.
No Codex log files were created or modified in the inspected `~/.codex/log`
and `~/.codex/logs` directories during that check. This is evidence for the
observed startup and discovery paths, not yet the Stage E error-redaction check.

## Evidence and continuation

- [Real-launcher protocol check](phase1-stage-b-stdio-2026-10-03.json).
- [Registration and preservation check](phase1-stage-b-codex-registration-2026-10-03.json).
- [Native Codex catalog discovery](phase1-stage-b-codex-runtime-2026-10-03.json).
- [Connected Codex project session](phase1-stage-b-codex-session-2026-10-03.json).

The connected session used the installed configuration in a fresh Codex runtime.
The current conversation's tool catalog was not refreshed dynamically; start a
new Codex session if the newly registered tools are absent here.

Next is Stage C, in the required order: `kie_get_credits`, `kie_search_docs`,
documentation/schema for a cheap model, `kie_estimate_cost`, then `dry_run=true`.
Stage C and paid generation remain unperformed. Stage D requires separate,
explicit owner approval of the concrete request before prepare/reserve/execute.
Stages E–G and Phase 1 owner acceptance remain outstanding.

Registration follows the [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
