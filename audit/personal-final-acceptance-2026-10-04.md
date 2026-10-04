# Personal image/video acceptance — 2026-10-04

## Result

All six friendly tools passed real secure-MCP prepare/execute/download; video passed
both text and image modes on Seedance 2.0 Mini. Seven successful tasks in one sequential
pass; no paid submission retries. Existing configured budgets/roots/key policy were
not changed. No media network request bypassed the project MCP.

Source evidence: `personal-sequential-acceptance-2026-10-04.json`.
Read-only inspection: `personal-result-metadata-2026-10-04.json`,
`personal-result-content-2026-10-04.json`, `personal-billing-summary-2026-10-04.json`.

| Tool | Task | Result |
|---|---|---|
| generate_video, text | private_id_c33bb8c1223c | MP4/H.264, 864×496, 4.041667s, no audio |
| generate_video, image | private_id_93e723581509 | MP4/H.264, 864×496, 4.041667s, no audio |
| generate_image | private_id_1ebf86a29e2d | PNG 1024×1024 |
| edit_image | private_id_211ad9bf6ef1 | JPEG 896×1200 |
| product_image_create | private_id_0be342d47608 | PNG 864×1184, white studio photo visually reviewed |
| remove_background | private_id_a66e11bb0e39 | RGBA PNG 387×516, 96,165 fully transparent pixels |
| upscale_image | private_id_80afaa408fd5 | JPEG 774×1032, exactly 2× input 387×516 |

Media remain in the configured external results root; no media binaries committed.
Alpha inspection is read-only: unchanged RGB behind transparent pixels is expected,
not evidence of a failed background mask. Box interior samples retain alpha 254/255;
background samples are zero. Human hands can remain foreground; this operation does
not promise product-only cleanup. Studio edit uses a separate paid tool.

## Checks

- 136 focused offline tests passed after friendly/core tariff changes.
- After Mini support, 102 pricing/friendly/service/ledger tests passed, including
  15 additional cases for duration/resolution/input conditions and promotion expiry.
- Ruff passed; Bandit exit 0, no findings (existing B105 annotation warning only).
- Friendly dry-run returns an exact payload/digest without reservation/submission.
- Strict schema mapping and price gates remain; unknown conditions require owner quote.
- Provider prices refreshed before execution; duplicate/ambiguous paid sends are not retried.

## Limits and billing evidence

Estimated successful-run total from live tariffs: $0.2035. Provider-reported per-task
credits sum to 40.7. Account balance moved from 548.01 to 488.23 (delta 59.78), leaving
19.08 credits unattributed by these task reports. Account history/owner reconciliation
is needed; account balance is not exclusive per-task attribution and no actual USD
was returned. Do not infer a global credit/USD rate or lower retained ledger liabilities.

The 480p preset produced 864×496 files. One Nano Banana edit returned JPEG despite
output_format=png. The MCP reports actual detected formats and does not convert them.
Video content motion/label fidelity was not frame-by-frame accepted; valid video
files/duration/streams were inspected with ffprobe. Studio image was visually reviewed.

Historical blockers remain in their original reports: Seedance Lite task
private_id_7489af36921c failed with provider Internal Error (creditsConsumed=0);
a parallel metadata run returned API code 429 before any paid image submission.
Owner authorized alternative preview and then the successful sequential pass.
The original Lite task was not resubmitted. Shared metadata rate limiting/health-aware
routing are not represented as implemented.

Mini pricing profile expires at 2026-10-07 06:00 UTC; expired/changed prose fails closed.
Timeline editing, deterministic animation/keyframes, audio-friendly tool, conversions,
all model/API family support and quality/speed scoring are not part of this acceptance.

KIE-side caps/model policy confirmation, Claude model-driven chat acceptance and final
owner sign-off remain external decisions. SaaS deployment is a separate backlog in
SAAS_READINESS.md. This report accepts the tested personal image/video workflows,
not every item in the complete specification or unattended production use.
