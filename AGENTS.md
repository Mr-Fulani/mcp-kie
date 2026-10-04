# Secure KIE media work

All media generation, editing, uploads, polling and result downloads must use this
project's secure KIE MCP tools. Never use kie-models, curl, a direct SDK or shell
network requests to bypass its budget, filesystem or approval guards.
kie-chat-agents remains permitted for independent chat-provider configuration.

Discover live model/schema/price, inspect dry-run, prepare one immutable request,
execute with its approval_id, wait and download into the configured results root.
Do not change owner configuration, spending caps, allowed roots, endpoints, DNS
validation, secret redaction or KIE-side policies through agent/MCP tools.

Never request secrets in chat or print them. Use the separate media Keychain entry.
A task timeout or unknown submission is not proof of rejection: never resubmit it
without owner reconciliation. Text instructions complement, not replace, OS and
KIE-key enforcement. Read SECURITY.md for the full threat boundary.

## Requirements and understandable approvals

Explain requirements and permission requests to this user in Russian. Before a tool
permission prompt, state the action, whether files leave the computer, and whether
money can be spent. Tool names and JSON field names may stay unchanged. Client-owned
buttons may remain English; never ask the user to approve text they do not understand.

Use kie_compare_models without an image for initial model choice; show supported
parameters, price/source/confidence and price_is_provisional/price_assumptions.
Wait for the user's selection. Then call kie_preflight before image upload, exact
preview or preparation; explain missing_inputs, field limits and provider format/size
descriptions in Russian. The preflight does not verify a local file. An exact image
preview may upload it to KIE; explain that before calling it. Before paid execution,
show confirmation_summary_ru and the chosen parameters, respecting existing user
authorization without duplicate approval questions.
