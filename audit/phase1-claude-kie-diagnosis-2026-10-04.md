# Claude authentication and KIE launch diagnosis

Date: 2026-10-04. The owner requested one retry and a concrete explanation of
the previous Claude error. The existing `kie-chat-agents` skill was used for
independent chat-provider diagnosis; no media API was accessed directly.

## Previous 401: launch-path cause established

The original acceptance script invoked `/LOCAL_OWNER/.local/bin/claude` directly.
Its environment had no `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_API_KEY` or `ANTHROPIC_MODEL`. The user-level Claude settings select
`claude-fable-5` but contain no KIE routing environment. That native run used
the existing Anthropic OAuth login and returned HTTP 401 with the exact error
`OAuth access token is invalid`. MCP itself was connected.

The user's `.zshrc` already defines `claude-kie`, `claude-kie-fable5`,
`claude-kie-opus55` and `claude-kie-sonnet55`. These set the KIE Anthropic base
URL and bearer-auth environment from the existing independent `KIE_API_KEY`.
The previous script bypassed these aliases. No new provider configuration or
new login is inherently necessary to select the user's existing KIE route.

## Authorized retry: timed out

One bounded native-client retry used the existing `claude-kie-fable5` alias
through an interactive zsh, with only balance/docs MCP calls permitted and
other media MCP operations denied. The process did not complete within 120
seconds and was terminated. The captured evidence contains no result or MCP
invocation event. Its timeout capture is not proof that no chat inference
reached KIE or incurred cost; actual chat consumption was not returned.

Brief focused read-only diagnosis then found:

- Interactive shell started successfully, resolved `claude-kie-fable5` as an
  alias, and confirmed the chat-key variable is present without exposing it.
- The process inventory after timeout contained no matching Claude/zsh process.
- One authenticated `GET https://api.kie.ai/anthropic/v1/models`, using only the
  existing chat key, returned HTTP **200** and included `claude-fable-5`.
  This was chat-model discovery, not inference or a media request.
- No model/provider/secret-policy configuration was edited.

The first retry's precise waiting stage was not established from its capture.
API-key acceptance and model-list availability do not prove that inference completes
normally. Under the owner's AGENTS.md blocker rule, permission was requested for
a further 2-3 minute diagnosis without MCP; the owner authorized that continuation.

## Minimal chat follow-up: 503 retry loop identified

One native `claude-kie-fable5` session requested only the literal answer `OK`,
with no MCP servers, no built-in tools, no session persistence and a short system
prompt. Incremental stdout/stderr were captured in memory throughout the run,
including before timeout; no secret literals were detected or saved.

The initialization event at 2.588 seconds confirms `claude-fable-5` and an empty
MCP server list. The request entered `requesting`, emitted a message-start event
at 12.813 seconds and message-stop at 12.939 seconds, without any content block
or final answer. Claude then emitted seven `api_retry` events with
`error_status=503`, `error=server_error` at 17.554, 20.563, 24.480, 29.201,
45.138, 57.570 and 76.905 seconds. Retry delays increased from 575 ms to
34,382 ms. The bounded run was stopped at 90.616 seconds, without a final result.

This establishes a reproducible chat-path 503/retry problem independent of MCP.
The retry loop explains why the client appears to wait without a response.
It does not establish the service's internal reason for returning 503, or prove
that the earlier 120-second run encountered identical events. A working model
listing and an initial message-start event do not prove successful inference.

The shell reported a gitstatus initialization warning but still started Claude
and sent the chat request. That warning is not the observed chat blocker and was
not repaired. The connector warning reflects explicit KIE authentication taking
precedence over the Anthropic account, as intended for this launch path.

User Claude settings, media owner configuration and `.zshrc` hashes were identical
before and after this follow-up. The stopped process group was terminated; no
configuration/dependency change, media request or additional model-switch test
was performed. No final chat usage/cost was returned, so this report does not
claim zero chat charges.

Recommended next options are to wait and retry the Fable route after service
recovery, or separately authorize a check through the already configured
`claude-kie-opus55` or `claude-kie-sonnet55` alias. Availability of these aliases
and model-list entries is not proof that their inference is currently healthy.
New provider configuration, reauthentication or key rotation is not indicated
by the accepted chat-key listing and observed 503 responses.

[Minimal chat events, timing and settings preservation](phase1-claude-minimal-chat-2026-10-04.json).

## Owner-requested retry during reported weak internet

The owner reported a weak internet connection and explicitly requested another
attempt. A new minimal native `claude-kie-fable5` request again used no MCP or
built-in tools, with earlier evidence preserved. This run captured events
incrementally and terminated the process group when the first API retry/error
was reported, rather than running another long automatic retry chain.

Claude initialized at 2.850 seconds, entered requesting at 2.869 seconds,
received a message-start event at 5.582 seconds and message-stop at 5.667
seconds without content. At 9.526 seconds it reported its first API retry with
`error_status=503`, `error=server_error`. The stopped run ended at 10.064
seconds; it did not reach a network timeout or produce a final answer/usage.

The transport delivered initial stream events, so the observed failure was
not simple inability to contact the API. This does not measure the user's
connection quality or exclude network issues between upstream services.
It confirms a repeated native-client report of 503 on the KIE Fable chat path,
independent of MCP, without establishing the internal cause of the 503.

Settings and shell configuration hashes were unchanged; the secret-literal
output scan found zero matches. No media operation or model-switch check was
performed. Under the owner's blocker rule, a separate choice was requested
before trying the existing `claude-kie-sonnet55` command for comparison.

[Short retry evidence](phase1-claude-minimal-chat-retry-2026-10-04.json).

## Sonnet comparison requested by owner

The owner approved a comparison using the existing `claude-kie-sonnet55` alias.
The same minimal request was sent without MCP or built-in tools. Claude
initialized as `claude-sonnet-5-5`, entered `requesting`, and reported its first
`api_retry` at 6.600 seconds with `error_status=503`, `error=server_error`.
The process was stopped immediately at 7.139 seconds before further retries.
Settings were preserved and the configured-secret scan found zero matches.

Fable and Sonnet therefore show the same KIE chat-path failure. The evidence
does not support a Fable-specific model problem, an MCP problem, or an invalid
KIE key. A weak local connection remains a possible contributor, but the
repeatable HTTP 503 after successful initialization on two models points more
strongly to a temporary KIE upstream/service or route problem. The direct
model-list GET still returns 200, so model discovery availability is separate
from inference availability.

Recommended action: wait for KIE chat service recovery and retry the existing
aliases later. Do not rotate the key, change MCP, or alter provider settings
based on this evidence. If the issue persists on a stronger connection, send
KIE support the timestamps and 503 symptoms; no secret or prompt needs to be
shared. Claude model-driven MCP acceptance remains pending.

[Sonnet comparison evidence](phase1-claude-sonnet-chat-2026-10-04.json).

For the user's existing KIE setup, launch `claude-kie-fable5` in a terminal
that loads `.zshrc`. Use plain `claude` plus a restored Anthropic login only
when intentionally selecting the official Anthropic account instead.

[Bounded KIE-alias retry evidence](phase1-claude-kie-tool-invocation-2026-10-04.json).
[Earlier direct-client OAuth error](phase1-client-tool-invocation-2026-10-04.json).
