# Secure KIE media instructions for an MCP client

Use the installed Secure KIE MCP tools for all media generation, editing, uploads,
polling and downloads. Do not bypass them with direct APIs, curl, SDKs, shell
network calls or another media skill. This does not govern independent chat login.

Without a specified model, show compatible live choices and their requested/default
parameters, price/source/confidence and limitations. Use kie_compare_models search
and next_cursor when more candidates are needed. Wait for the user's model choice
unless they explicitly delegated selection. auto_select=true means cheapest known
compatible price among the first 20 candidates; it is not quality/health ranking.
Do not fabricate quality ratings, speed estimates or a zero price for unknown costs.

With the chosen model, inspect dry_run before preparing. Explain that exact image
preview may upload the source; comparison does not. Prepare one immutable request,
then execute only its approval_id with unchanged model/input in the same session.
Follow the user's existing authorization; avoid requesting approval twice for the
same reviewed action. Do not silently add other paid steps or substitute parameters.

Never request/paste/print secrets, alter owner config/caps/roots/endpoints, create
an owner quote or change KIE-side key policy. Owner setup uses Keychain, a private
secret file, Docker Secret or explicit dev environment. The local doctor is an
owner-run read-only CLI, not an MCP config/secret management tool.

A timeout/unknown submission is not rejection. Do not resubmit without owner
reconciliation of provider history. Keep task IDs and budget liabilities intact.
Download successful results to the configured root, optionally with a short
result_label; it is text, not a path. Show output_path/output_folder to the user.
Never delete old media or reset the usage ledger to make a task pass.

Read SECURITY.md for the full boundary. These instructions do not isolate an agent
with shell/network access under the same OS user; stronger isolation requires an
owner-managed OS/container deployment.
