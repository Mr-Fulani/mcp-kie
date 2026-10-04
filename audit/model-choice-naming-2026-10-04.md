# Model choice and readable result folders

Acceptance on 2026-10-04 through a fresh secure project stdio MCP process.
No paid generation was submitted. Owner limits, roots and key policies were unchanged.

- 23 MCP tools were discovered, including `kie_compare_models`.
- `generate_image` without a model returned five live candidates and required user
  selection, without upload, reservation or executable approval. Nano Banana had a
  recognised $0.02 tariff; other inspected prices remained unknown, not zero.
- Seedance video comparison returned schema compatibility, duration/resolution/audio
  controls and effective settings. Mini defaulted to audio enabled; that pricing
  branch was unknown under the reviewed personal profile. User must select supported
  settings or obtain an owner quote. No independent quality/speed scores were claimed.
- Existing successful task `private_id_c33bb8c1223c` was downloaded again via
  `kie_download_result(result_label="mini-video-test")`. The new folder was
  `2026-10-04__mini-video-test__video__bytedance-seedance-2-mini__caafeb668a580430b3cafdad08042702`.
  The new MP4 was nonempty; filenames and sizes in the original task-ID folder
  remained identical. No existing folder was renamed or moved.

Local verification: 151 focused regression checks passed, followed by eight comparison
checks after adding a new freshness scenario. The freshness test changes catalog,
schema and price between calls and verifies all three are fetched again (152 unique
checks across the two runs). Ruff, Bandit and diff whitespace checks passed.
Storage checks cover Unicode byte bounds, traversal, model paths, symlink escape,
full task identity and repeated publication without overwriting old files.

Every comparison fetches live metadata; it is a snapshot of KIE's published catalog,
not a provider-availability guarantee. Required metadata errors do not use stale
fallback comparisons. Prepare/execute guards remain separate, and execution refreshes
schema and price again. Explicit cheapest selection is limited to the first 20
catalog candidates. Restart existing MCP clients to load new tools and arguments.

Structured results: [model-choice-naming-2026-10-04.json](model-choice-naming-2026-10-04.json).
