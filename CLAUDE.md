Media operations must use the secure KIE MCP prepare/execute path exclusively.
Read AGENTS.md and SECURITY.md. Do not invoke direct paid media API requests or
change owner security/budget policy. The independent chat key is not a media key.

Explain requirements and permission prompts in Russian, including file transfers
and possible costs. Initial comparison requires no photo. After model choice, call
kie_preflight before uploads/preview/prepare and explain missing inputs and limits.
Show confirmation_summary_ru and parameters before paid execution; respect existing
authorization. Client-owned buttons may remain English; explain their meaning first.

Without an explicit model, friendly tools return choices. Show compatible options,
parameters, price/confidence and source to the user before preparing their chosen
model. Use kie_compare_models with next_cursor to inspect further candidates.
Do not invent quality/speed scores. auto_select=true is allowed only when the user
explicitly delegates cheapest selection. Downloads use readable folders for new
saves only; optionally supply result_label as short text, never a path.
