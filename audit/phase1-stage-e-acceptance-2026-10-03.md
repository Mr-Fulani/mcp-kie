# Phase 1 - Stage E: installed MCP security acceptance

Date: 2026-10-03. Result: **PASS** for the checks described below.

The installed Keychain launcher initialized over local stdio with all 22 tools.
Fifteen negative tool calls returned errors and no task, approval, upload data
or output path: SSH file, parent traversal, outside-root media, symlink escape,
forbidden extension, fake image content, oversized media, fake base64 media,
IPv4 loopback, private network, metadata endpoint, IPv6 loopback, plain HTTP,
private download-link URL, and paid creation without an approval ID.

The symlink pointed only to a harmless outside-root sentinel. The oversized
fixture has 52,428,801 logical bytes and occupies 20,480 disk bytes. Fixtures
were retained; no user files were altered or deleted. Their paths are recorded
in the evidence. No valid media was uploaded and no paid task was submitted.

Captured stdout (12,741 bytes) and stderr (2,592 bytes) contained zero literal
matches for the configured media/chat secrets. These values were compared only
in memory, never saved in evidence. Returned errors did not echo private file
paths. The owner configuration bytes were preserved. Read-only ledger snapshots
before and after were identical, containing the one earlier successful task.

Four additional negative calls from the current native Codex tool interface
also passed. The full error-output scan used a fresh installed stdio process;
it does not claim a complete scan of all existing client log history.

The live download tool schema exposes only `task_id` and `result_index`, with
no caller-controlled path. Stage D already demonstrated a real download inside
the configured results root. Download symlink/atomic-write and multi-process
race regression tests remain covered by the existing offline baseline; these
were not repeated during this report/configuration-only task.

Evidence:

- [Fresh-launcher negative calls and secret scan](phase1-stage-e-runtime-2026-10-03.json).
- [Native Codex negative calls](phase1-stage-e-native-2026-10-03.json).
- [Earlier real download](phase1-stage-d-download-followup-2026-10-03.json).

Remaining Phase 1 work includes the local product-image functional scenario,
owner confirmation of KIE-side policy, further client session acceptance as
needed, and the final owner acceptance report.
