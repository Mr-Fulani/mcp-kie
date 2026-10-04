# Personal friendly tools: partial acceptance — 2026-10-04

Historical intermediate report. Final outcome supersedes the pending checks below:
[personal-final-acceptance-2026-10-04.md](personal-final-acceptance-2026-10-04.md).

## Complete

- All six friendly tools expose `dry_run` and `model_input` through actual stdio
  tool discovery. `edit_image`/`product_image_create` expose output format.
- Conservative mappings are bound to live declared fields; string duration and
  enum case normalization; one required primary image instead of optional last frame.
- Extra fields must exist in the schema; duplicate parameters and ambiguous inputs
  fail closed. JSON Schema validation and all financial gates remain in place.
- Automatic routing skips unsupported unified API contracts; explicit model errors
  are retained. Selection still only compares known costs within first 20 candidates.
- Existing trusted KIE input URLs are reused; external/local sources are uploaded
  only after a compatible model is selected. Public-DNS/URL guards still apply.
- Exact previews return unknown pricing with `next_step=owner_verified_quote` and
  no reservation. No agent price/quote/policy override was added.
- 88 focused offline tests passed in 3.57s: friendly/service/security/ledger/storage.
  Ruff passed; Bandit exit 0, no findings (existing B105 annotation warning only).

## Live secure MCP checks

Fresh `kie-mcp-launch` stdio process, separate Keychain secret; only tool protocol
calls. No shell/direct SDK media network requests. Evidence:
`personal-friendly-live-preview-2026-10-04.json`.

| Tool / model | Result |
|---|---|
| generate_video / bytedance/v1-lite-text-to-video | Schema-valid preview: duration `"5"`, 480p, 16:9 |
| generate_video / bytedance/v1-lite-image-to-video | Schema-valid preview: primary image_url, duration `"5"`, 480p |
| edit_image / google/nano-banana-edit | Schema-valid preview with output_format=png and aspect_ratio=3:4 |

All three returned `confidence=unknown`, `reservation_created=false`.
No paid request, video output or video download occurred. Image-to-video preview
reused an earlier KIE upload URL; it does not prove that the provider still retains
that temporary file or that rendering succeeds.

## Concrete blocker and next decision

The live price endpoint supplies prose/conditional tariffs outside the current
strict price grammar. Seedance Lite describes ~$0.010/s at 480p (~$0.05 for 5s);
Nano Banana describes ~$0.02/image. These are metadata, not an accepted executable
quote. No price was guessed and no owner configuration was changed.

Recommended next work: implement reviewed tariff support for the selected personal
models with precise parameter conditions and fail-closed regression tests. Expected
extra work: roughly 30–60 minutes, subject to live schema/tariff complexity. Alternative:
owner-reviewed exact-request quotes for a limited smoke test; it does not solve
everyday automatic selection/pricing.

During preview Nano Banana also applied deprecated `image_size=1:1` alongside
explicit `aspect_ratio=3:4`. Resolve legacy defaults or verify provider precedence
before claiming paid friendly editing acceptance.

Per the user's AGENTS.md blocker rule, no expanding price/default remediation or
paid generation is undertaken before the owner's next decision. Outstanding KIE-side
caps confirmation, Claude model-driven invocation, real video/removal/upscale tests
and final owner acceptance are not represented as complete.
