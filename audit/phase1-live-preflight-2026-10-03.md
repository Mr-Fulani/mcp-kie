# Phase 1 live acceptance: stage A preflight

Date: 2026-10-03. Current status: stage A passed after owner authorization.
Verified follow-up evidence: `phase1-stage-a-runtime-2026-10-03.json`.

## Owner-approved follow-up: PASS

- Successfully loaded `kie-mcp-media` / `media` from macOS Keychain without
  printing or saving the key. Its value differs from the available chat key.
- Created `/LOCAL_OWNER/.config/kie-mcp/config.toml` with mode 0600 and no secret
  fields. The launcher sets only `KIE_MCP_API_KEY` for media authentication and
  removes `KIE_API_KEY` from the child environment; no chat-key fallback exists.
- Created and verified the approved uploads/results/state directories with mode
  0700, current-user ownership and read/write/search access. Existing ancestor
  directory permissions were preserved.
- Verified the effective launcher settings: USD 1/task, 5/session, 10/day,
  100/total; concurrency 5; upload limit 50 MiB; transport stdio.
- Scanned 48 tracked or unignored project files and the installed owner config
  for the configured media/chat secret literals: zero matches. Values were not
  included in the report or command arguments.
- Shared ledger path is `/LOCAL_OWNER/.local/share/kie-mcp/usage.db`; the state
  directory is ready, and the database has not yet been created.
- No KIE requests, billable tasks, client registrations or account-policy changes
  were made. Stages B-G remain unstarted. Application code/dependencies and the
  accepted 73-test baseline were unchanged.

## Initial blocked attempt (retained history)

The following observations describe the initial attempt before the owner saved
the media key and authorized installation of the runtime configuration.
The existing local implementation and 73 passing tests are the accepted baseline;
no application code or dependencies were changed for this preflight.

## Confirmed

- MCP's primary secret is `KIE_MCP_API_KEY`; no fallback to `KIE_API_KEY` exists.
- The launcher captures the dedicated media secret and removes the chat key from
  the child environment. No secret value was printed or written to this report.
- `KIE_MCP_API_KEY` is absent from the inspected environment; a chat key is present.
  Its value was neither printed nor used for media operations.
- Selected secret source is macOS Keychain, with the default service
  `kie-mcp-media` and account `media`.
- A read-only diagnosis outside the filesystem sandbox still could not load the
  configured media secret. Keychain metadata lookups for services `kie-mcp-media`
  and `for-mcp-media` both returned 44 (item not found in the searched keychains).
- The owner reports that the KIE account already has a separate key named
  `for-mcp-media`. Creating that key in KIE and storing it in the local Keychain
  are separate steps; this check did not inspect or modify the KIE account.

## Runtime configuration

| Item | Observed result |
|---|---|
| `~/.config/kie-mcp/config.toml` | Missing |
| Upload root | Not configured |
| Download root | Not configured |
| Example `~/Projects/kie-workspace/uploads` | Missing |
| Example `~/Projects/kie-workspace/results` | Missing |
| `~/.local/share/kie-mcp` ledger directory | Missing |
| Transport | `stdio` |
| Per-task budget | Default USD 1.00 |
| Per-session budget | Default USD 5.00 |
| Daily budget | Default USD 10.00 |
| Total budget | Default USD 100.00 |
| Concurrency | Default 5 |
| Upload limit | Default 50 MiB (52,428,800 bytes) |
| Download limit | Default 100 MiB |

Directories are absent, so their ownership/permissions cannot yet be accepted.
KIE-side caps, Allowed Models and IP whitelist were not read or modified.

## Smallest next step requiring owner input

1. Store the existing `for-mcp-media` key in Keychain Access as service
   `kie-mcp-media`, account `media`, or supply only the service/account of its
   existing dedicated Keychain item. Do not supply the secret in chat or CLI args.
2. Review `phase1-owner-config.proposed.toml`. Its proposed destinations are
   `~/.config/kie-mcp/config.toml`, the two example media directories above and
   `~/.local/share/kie-mcp` for the shared persistent ledger. Proposed owner config
   mode is 0600; new runtime directories are 0700.
3. Obtain owner authorization before creating that configuration/directories,
   then repeat stage A. No application tests/builds or paid request are needed.

Stages B-G have not started. No Codex/Claude/Grok registrations were changed,
no KIE network request or billable task was made, and no usage ledger was created.
The Codex registration diff will be prepared only after stage A succeeds.
