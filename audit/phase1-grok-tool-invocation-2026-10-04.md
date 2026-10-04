# Phase 1 - Grok native MCP tool invocation

Date: 2026-10-04. Result: **PASS with one recovered argument error**.

After the Claude OAuth blocker, the owner explicitly selected a Grok-only
check and deferred Claude until login restoration. The installed Grok client
used its existing `kie-47` profile (`grok-4.7` in the reported model usage).
No model/provider configuration was changed.

The native session discovered the installed `kie-media` catalog through
`search_tool`, then invoked the secure server through `use_tool`:

- `kie_get_credits` with `{}` returned code 200 and account balance 837.73.
- `kie_search_docs` with query `z-image` and limit 2 returned
  `source=live_docs_index` and two official documentation links.

The first attempted balance invocation omitted `tool_input`. Grok rejected
that meta-tool argument before MCP dispatch; the model supplied `{}` on its
next attempt and successfully completed both required calls. This is an
observed client argument error followed by successful recovery within the same
session, not an extra acceptance run or a media-task retry. The native process
exited zero with a non-error final result.

The verification script initially marked BLOCKED because it rejected every
intermediate tool error. Focused inspection of the saved tool-use/result IDs
and actual MCP output established successful completion. The original validator
status/error are retained in evidence alongside the reviewed result. No check
was repeated and no additional chat request was submitted during review.

No paid media task, reservation, upload, file-edit tool, shell tool or subagent
invocation was observed. The CLI used `dontAsk`, explicit allow rules for the
two read tools and deny rules for all other media MCP tools. Grok's reported
startup inventory still listed built-in tools despite `--tools ""`; this report
does not claim they were removed from that inventory. Only search/use meta-tools
were actually invoked.

Configured media/chat secret literal scan found zero output matches. Current
Grok configuration SHA-256 matches the accepted registration revision, and the
media owner configuration matches the authorized product-quote installation.
Claude's native runtime bookkeeping is not claimed byte-for-byte unchanged.

The client reported chat cost **USD 0.118782**. This is Grok's reported chat
cost, not a media charge or an independent provider-billing reconciliation.
The account-wide balance snapshot cannot attribute spend to this session.

[Redacted native session and reviewed evidence](phase1-grok-tool-invocation-2026-10-04.json).

Claude model-driven invocation remains deferred after its 401 OAuth error.
KIE-side caps/model-policy confirmation and final overall Phase 1 owner
acceptance remain outstanding.
