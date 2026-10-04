# Phase 1 — Stage C: live discovery and dry-run

Date: 2026-10-03. Result: **PASS** after explicit owner-approved quote
installation and live verification at 12:21:02 UTC. The initial run was PARTIAL
because automatic pricing was unknown; its evidence is retained below.

Baseline commit: `e3ce4e6fab8c766d634d798dd3ca617960f9bfcc`.
The current Codex session exposes all 22 installed `kie-media` stdio tools.
Every KIE/docs request used secure MCP tools; no direct KIE API or shell
network request was used. The follow-up used a fresh stdio MCP client running
the installed Keychain launcher, so it loaded the updated owner configuration.

## Owner-approved quote follow-up: PASS

The owner explicitly confirmed USD 0.004 and 0.8 credits per `z-image`
generation, citing <https://kie.ai/pricing>, and authorized quote installation,
the configuration-path addition, estimate and dry-run. Paid generation was
explicitly withheld. This authorization overrides the general instruction
against agent edits to owner configuration for these exact changes only.

- Quote: `/LOCAL_OWNER/.config/kie-mcp/owner-quote-z-image.json`, mode `0600`.
- Owner config: `/LOCAL_OWNER/.config/kie-mcp/config.toml`, mode `0600`.
  Added only `KIE_OWNER_QUOTE_PATH` in the existing `[environment]` section.
  Other settings and their values were preserved.
- Private original-config backup, mode `0600`:
  `/LOCAL_OWNER/.config/kie-mcp/config.toml.owner-quote-backup-private_id_6a00ed805004`.
  Its bytes match the reviewed pre-change configuration.
- Quote bound: USD `0.004`; estimated credits `0.8`; `approved_by_owner=true`.
  The quote is bound to the exact request digest shown below.
- Created at 12:20:56 UTC; expires at **12:50:56 UTC / 15:50:56 Europe/Istanbul**
  on 2026-10-03 (30 minutes from installation).

| Check | Observed result | Result |
| --- | --- | --- |
| Fresh installed launcher | Secure KIE media over stdio; all 22 tools | PASS |
| Protected estimate | USD 0.004 / 0.8 credits, `confidence=estimated`, `owner_approved=true` | PASS |
| Quote source | `owner_verified_quote:https://kie.ai/pricing` | PASS |
| Explicit dry-run | Same validated payload, request digest and schema digest | PASS |
| No paid side effects | `dry_run=true`, `reservation_created=false`; no `approval_id` or `task_id` | PASS |
| Ledger | Database, WAL and SHM files still absent | PASS |

## Initial results before the owner quote

| Check | Evidence | Result |
| --- | --- | --- |
| Media-key authentication | `kie_get_credits`: code 200, balance 506.53 credits | PASS |
| Official documentation search | `kie_search_docs`: `source=live_docs_index` | PASS |
| Live model discovery | `kie_list_models`: 34 entries tagged Text to Image | PASS |
| Cheap test candidate | `z-image`, published base tariff 0.8 credits/image (approximately USD 0.004) | FOUND |
| Official model documentation | Z-Image Markdown retrieved; bounded 10,000-character excerpt | PASS |
| Live unified schema | Required input fields `prompt`, `aspect_ratio`; endpoint `/api/v1/jobs/createTask` | PASS |
| Protected cost estimate | `confidence=unknown`; estimated USD and credits both null | BLOCKED |
| Explicit dry-run | `dry_run=true`, `reservation_created=false`, unchanged request/schema digests | PASS |
| Runtime ledger | Database, WAL and SHM files absent after dry-run | PASS |

Documentation: <https://docs.kie.ai/market/z-image/z-image.md>.
The Markdown response intentionally reports `truncated=true` at the requested
excerpt limit. The separate live schema response is complete.

## Exact reviewed request

```json
{
  "model": "z-image",
  "input": {
    "prompt": "A single small green leaf centered on a plain white background, soft natural light, no text.",
    "aspect_ratio": "1:1"
  }
}
```

Request digest:
`80c20d439ee1efaa8e9f227f335d449d82c2ccb4625ac70e83298c304b19200b`.
Schema digest:
`51cd6464ec76efb93c596cda871555059ce2fbbe23857757df24e2c30305b3b6`.
Both digests agree across the schema, estimate and dry-run where applicable.

## Initial pricing blocker and approved resolution

Live pricing source: `live_kie_metadata:/api/v1/models/z-image/price`.
The returned description states a flat 0.8 Kie credits per image
(approximately USD 0.004) and a discounted top-up rate. This prose does not
match the deliberately narrow complete unconditional tariff grammar in
`src/kie_mcp/models.py`. It is a published tariff, not a verified spending bound.
No owner quote was applied in the initial run. The explicitly authorized
exact-input quote resolved this blocker through the existing supported path.
The automatic pricing parser, security guards and dependencies were unchanged.

## Ready for Stage D; stopped before paid work

The exact request above is ready for a separately approved single-image test:
`z-image`, a small green leaf on white, aspect ratio `1:1`, USD 0.004 /
0.8 credits. Before Stage D, the MCP process must load the updated configuration
and the quote must remain unexpired. A later request requires owner-approved
quote renewal if this quote has expired.

No prepare/reserve/execute was called. Stage D still requires separate explicit
owner approval of this concrete paid request. After approval, prepare and
execute must use the unchanged model/input in one MCP session, followed by wait
and download into the configured results root.

No budget reservation, paid submission, upload, polling or result download
occurred. The owner configuration gained only the approved quote path; spending
caps, roots, endpoints and other policy values were preserved. Application code
and dependencies were unchanged. No commit or push was made for these reports.
Stages D–G remain unperformed.

## Evidence

- [Live MCP responses and dry-run](phase1-stage-c-live-dry-run-2026-10-03.json).
- [Owner-approved quote installation and fresh-runtime verification](phase1-stage-c-owner-quote-runtime-2026-10-03.json).
- [Earlier Codex stdio acceptance](phase1-stage-b-acceptance-2026-10-03.md).

Verification covers live estimate/dry-run, quote/config/backup permissions and
content, preservation of other owner settings, request/schema consistency,
ledger absence, evidence links and diff formatting. No application build or
unrelated test suite is required for these configuration and audit changes.
