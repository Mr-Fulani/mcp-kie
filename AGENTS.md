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
