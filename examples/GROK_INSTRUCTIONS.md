Media operations must use Secure KIE MCP exclusively. Discover current schemas and
pricing, inspect dry-run, prepare, execute the unchanged payload, poll and download.
Never bypass guards with direct API/skills/shell media generation. Do not change
owner limits/roots/endpoints or use the chat key for media. Read SECURITY.md.

Without an explicit model, friendly tools return choices. Show compatible options,
parameters, price/confidence and source to the user before preparing their chosen
model. Use kie_compare_models with next_cursor to inspect further candidates.
Do not invent quality/speed scores. auto_select=true is allowed only when the user
explicitly delegates cheapest selection. Downloads use readable folders for new
saves only; optionally supply result_label as short text, never a path.
