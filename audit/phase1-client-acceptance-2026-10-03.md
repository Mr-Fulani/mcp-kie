# Phase 1 - Claude Code and Grok Build registration/connectivity

Date: 2026-10-03. Result: **PASS for native CLI connectivity**.

The owner instructed continuation of the outstanding specification work.
Only a separate `kie-media` user registration was added to each client:
`/LOCAL_OWNER/.claude.json` and `/LOCAL_OWNER/.grok/config.toml`. Both use
`/LOCAL_OWNER/mcp-kie/.venv/bin/kie-mcp-launch`, empty arguments and stdio.
Grok additionally sets `enabled=true`. No key or secret environment value
was added to either configuration.

Private mode-0600 backups match the original configuration bytes. Parsing
each updated configuration and removing only the new entry reproduces the
original settings. Providers, aliases, defaults and unrelated settings were
preserved. A second registrar preview reports no change for each client.

Native verification passed:

- `claude mcp get kie-media`: user-scoped registration, `Connected`, stdio,
  expected launcher and no arguments.
- `grok mcp doctor kie-media --json`: command found, server started,
  handshake protocol `2025-11-25`, 22 tools discovered, `healthy=true`,
  `healthy_count=1`, `failing_count=0`.
- Both commands exited zero with empty stderr. Captured output contained
  zero literal matches for the configured media/chat keys.

The media owner configuration was preserved. No model turn, generation,
upload, account-policy change, application-code edit or dependency change
occurred. These checks establish native client connectivity/discovery;
model-driven tool invocation in Claude/Grok has not yet been performed.
Codex's earlier session acceptance is recorded separately in Stage B.

See [registration preservation, backup paths and native CLI evidence](phase1-client-acceptance-2026-10-03.json).
