# Phase 1 - local product-image functional acceptance

Date: 2026-10-03. Result: **PASS** for the local-image edit/download scenario
in specification section 32, with the separately authorized local WebP conversion.

The owner supplied `/LOCAL_OWNER/Projects/kie-workspace/uploads/images.jpg`
(20,934 bytes, validated JPEG) and requested a studio product photograph and WebP.
The file was uploaded only through `kie_upload_local_file` to the trusted KIE
input host. Live catalog/schema/docs selected `google/nano-banana-edit`.

The owner replied "да" after reviewing one generation at 4 credits / approximately
USD 0.02, installation of a 30-minute exact-input quote, and an exception permitting
offline lossless WebP conversion. Only the approved quote path was changed in the
private owner configuration, with a verified private backup. Spending caps,
media roots and endpoint/security settings were preserved. The previous quote
file was retained. The new quote expires automatically; no renewal is authorized.

A fresh installed Keychain stdio launcher loaded the quote and all 22 tools.
Estimate, dry-run, prepare and execute used the unchanged payload and digest.
Exactly one paid submission occurred, followed by wait and secure result download.

- Model: `google/nano-banana-edit`.
- Task: `private_id_02acf1578091`.
- Request digest: `5b2bc3af6021f78a18a05b274faed7f2fa59608d4c39d94abaf445b089543b3c`.
- Output: PNG, 864 x 1184, 724,805 bytes; WebP, 523,604 bytes.
- Provider/ledger actual consumption: **4 credits**, one output, `status=success`.
- Provider actual USD was not returned; USD 0.02 remains the approved estimate.

The PNG was downloaded through secure MCP into the configured task results
directory. The already-installed `cwebp` encoded that PNG offline in lossless
exact mode. A new server-named WebP was published without replacement in the
same task directory; the PNG and original JPEG remain intact. FFmpeg decoded
both files into RGBA pixels and their SHA-256 values matched. No dependencies
were installed or changed. Captured MCP stdout/stderr had zero configured-key
literal matches. No second generation or direct KIE SDK/network call occurred.

Visual review passed: white studio background, soft contact shadow, carton
upright, household background/hand removed, main brand/dose/manufacturer labels
preserved. Enlarged inspection confirms "100 überzogene Tabletten" in the upper
line. This is a visual review, not validation of tactile Braille encoding or
pixel-for-pixel identity to the original carton. The requested 3:4 parameters
produced the provider's actual 864 x 1184 canvas, without further cropping.

[Exact request, installation, MCP responses, ledger and output paths](phase1-product-thiola-runtime-2026-10-03.json).

KIE-side caps/model-policy confirmation, model-driven Claude/Grok invocation
and final overall Phase 1 owner acceptance remain outstanding. This run tests
the low-level secure image workflow; it does not establish full friendly-tool,
intelligent-router or SaaS acceptance.
