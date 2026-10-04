# Phase 1 — Stage D: single paid generation

Date: 2026-10-03. Result: **PASS** after the owner-authorized exact-host
review and secure download follow-up. One `z-image` generation succeeded,
consumed 0.8 credits and produced a verified 1024 × 1024 PNG. The initial
blocked download is retained in the original evidence.

## Completed work

- Owner authorized the exact Stage C request with “ок, погнали” after reviewing
  the model, input and USD 0.004 / 0.8-credit price.
- The quote was unexpired and matched the unchanged request. Configuration and
  quote contents were preserved from the accepted Stage C revision.
- A fresh installed Keychain launcher connected over stdio with all 22 tools.
- `kie_prepare_task` created one reservation for USD 0.004 / 0.8 credits.
- `kie_execute_task` was called exactly once with the returned approval ID and
  unchanged model/input in the same MCP session.
- `kie_wait_for_task` returned `state=success`, `creditsConsumed=0.8`, one
  result URL and provider generation time `costTime=13` seconds.
- Read-only ledger inspection confirmed `status=success`, `actual_credits=0.8`
  and `output_count=1`. Provider USD usage was not returned; the recorded USD
  estimate remains 0.004. No second generation was submitted.

Approval ID: `private_id_e6e6e774a399`.
Task ID: `private_id_2c5ea4dacca0`.
Request digest:
`80c20d439ee1efaa8e9f227f335d449d82c2ccb4625ac70e83298c304b19200b`.
Input: one small green leaf centered on white, soft natural light, no text,
aspect ratio `1:1`; model `z-image`.

## Initial download blocker and approved resolution

`kie_download_result` returned:

```json
{
  "error": "URL host is outside the network allowlist",
  "blocked": true
}
```

The authenticated KIE task response pointed to `tempfile.aiquickdraw.com`.
The original allowlist contained `tempfile.redpandaai.co` and `file.kie.ai`.
The guard rejected the new host and created no local image in that initial
run. The saved tool response identifies the cause; the original live-generation
JSON remains `PARTIAL` as a record of that run.

The first read-only SQLite inspection was restricted by the shell sandbox.
A read-only inspection with the required filesystem permission succeeded.
No ledger data or security setting was edited during diagnosis.

Work paused for the owner's decision under the supplied AGENTS.md blocker
rule. The owner then explicitly authorized review of this exact host,
its addition if verified, and download of the existing completed task.
[SECURITY.md](../SECURITY.md) requires explicit review of new storage hosts.

Review passed: a fresh authenticated task response confirmed the same task
and result host; every resolved address was public; the TLS certificate chain
and hostname were verified through a connection to a validated numeric address.
The host review sent no HTTP request, API key or media download.

Only `tempfile.aiquickdraw.com` was added to `KIE_STORAGE_HOSTS` in
`src/kie_mcp/network.py`. HTTPS, public pinned DNS, certificate verification,
redirect checks and byte limits were preserved. Generation-input URLs remain
restricted to `tempfile.redpandaai.co`. Documentation and focused network tests
were updated. Dependencies, owner configuration and spending caps were unchanged.

A fresh installed stdio launcher loaded the change and called only
`kie_get_task`, `kie_download_result` and `kie_get_credits`. The existing
completed task was downloaded through secure MCP. No second generation,
direct API/SDK/browser download or quote renewal occurred. The quote was valid
at submission; its later expiry did not prevent downloading the completed task.

## Downloaded result

- [Verified PNG](../../Projects/kie-workspace/results/private_id_2c5ea4dacca0/private_id_0d250540a5fd.png).
- Format: PNG, 1024 × 1024; 1,019,303 bytes; mode `0600`.
- Stored inside the configured task results root.
- All PNG chunk CRCs and the complete IEND were verified.
- Visual inspection passed: one green leaf centered on white, no text.
- SHA-256:
  `05deff1dd882a0b1b78745ce99fec6fe0f58a3647b59db7916270f7a39040d6b`.

The ledger was identical before and after download: one matching request row,
`status=success`, `actual_credits=0.8`, `output_count=1`. Actual USD usage remains
unreported by the provider; USD 0.004 is the owner-approved estimate.

## Shared account balance

The observed balance changed from 120.59 before generation to 31.83 after
download, a decrease of 88.76 credits. The owner subsequently confirmed that
another agent uses this same account balance through a different API key.

The [official credits documentation](https://docs.kie.ai/common-api/get-account-credits.md),
retrieved through secure MCP, describes the endpoint as: “Get the current
credit balance available in your account.” These are account-wide credit
snapshots, not per-key spend or chat token counts. Their difference cannot
measure the cost of this single task.

The provider task response and local ledger both confirm **0.8 credits** for
this generation, matching the owner tariff. The remaining 87.96 credits are
the arithmetic difference after subtracting that charge; other account
transactions were not individually audited or attributed.

## Evidence and verification

- [Live tool responses, single submission and diagnosis](phase1-stage-d-live-generation-2026-10-03.json).
- [Owner-authorized storage-host review](phase1-stage-d-storage-host-review-2026-10-03.json).
- [Secure download, ledger, balance clarification and image verification](phase1-stage-d-download-followup-2026-10-03.json).
- [Accepted Stage C quote and exact request](phase1-stage-c-acceptance-2026-10-03.md).

Focused verification for the network change passed: **68 tests** across
`test_network_storage.py`, `test_security.py`, `test_client.py` and
`test_service.py`; Ruff passed for the changed code and tests. Audit-file
checks cover evidence consistency, links and formatting. The completed tests
were not repeated for the report-only follow-up.

Stage D is complete. Stages E–G and overall Phase 1 acceptance remain
outstanding. No further phase, generation, commit or push was performed.
