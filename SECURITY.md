# Security policy and threat model

Transport is **local stdio only**. Paid tasks require immutable prepare/execute.
This is a local defense-in-depth boundary, not isolation of an independent
shell/network-enabled coding agent under the same OS account. Live acceptance and
external key policy must still be completed before unattended use.

## Secrets and errors

Use a separate media Keychain item (`kie-mcp-media`, account `media`), an owner-only
local `secret_file`, or a dedicated Docker Secret. On local Linux/WSL2, the file
is plaintext: owner UID, regular-file status, mode 0600/0400, a 16 KiB bound and
O_NOFOLLOW/O_NONBLOCK are checked. This does not encrypt the key or isolate a
same-user agent; protect the parent directories and disk. The launcher executes only the fixed `/usr/bin/security`
read-password operation, with shell disabled, stdout captured and stderr discarded.
The key is passed only through the child environment; the chat key is removed.
Development environment fallback is explicit. Keys are excluded from Settings repr.
No MCP tools manage keys/policies. Owner config is read with a bounded,
owner-only, regular-file/O_NOFOLLOW check; unknown names/sections, boolean values,
relative paths and an explicit missing config fail startup. Numeric byte limits
and timeouts must be positive/finite. These checks do not alter stored owner caps. Do not store secrets in owner config, CLI args,
client configuration, Git, `.env` on a production Mac or shell history.

Provider responses are recursively redacted before use; fixed unexpected-error
messages suppress tracebacks and private input. Schema validation errors do not
echo input values. Ledger metadata stores hashes, not raw prompts/file content.
No raw prompt/base64 logging is implemented. Known allowed output paths are returned
so users can find their files. Code does not claim protection against process-memory
inspection or another same-user process reading child environments.

## Filesystem sandbox

Local upload is opt-in with an owner root. Reject traversal and forbidden suffixes;
canonical paths must remain in root. Anchored directory descriptors, O_NOFOLLOW,
fstat and a bounded snapshot prevent symlink swaps and growth during transmission.
Magic signatures reject obvious disguised secret/script/archive content. They do
not fully decode media or detect polyglots/malware. MIME validation is not a content
privacy filter: an agent can upload data it already obtained outside MCP.

Only completed-task result URLs are downloaded; caller selects an index, not a path.
Result downloads accept only the explicit KIE storage hosts `tempfile.redpandaai.co`,
`file.kie.ai` and `tempfile.aiquickdraw.com`; redirect targets are checked by the
same HTTPS/DNS policy. The last host was added after explicit owner authorization,
an authenticated completed-task response, public-DNS validation and TLS hostname/
chain verification; see `audit/phase1-stage-d-storage-host-review-2026-10-03.json`.
Task identifiers and model identifiers are constrained; filenames are generated.
New folder names contain UTC date, detected media type, bounded model slug and full
task ID, with an optional validated 48-byte text label. Labels never provide paths,
prompts are not used, and existing folders are not migrated. A private temporary file
inside an anchored result directory is fsynced and atomically hard-linked into place
without replacement, then unlinked and the directory fsynced. A failure can leave
an incomplete `.part` artifact; there is no unsolicited cleanup. Owner must protect
configured roots and their ancestors from replacement by untrusted OS processes.

## Network, SSRF and DNS

API origins are fixed: `api.kie.ai`, documentation `docs.kie.ai`, upload
`kieai.redpandaai.co`, and the three explicit KIE storage hosts above. No MCP tool
accepts a base URL, arbitrary endpoint, proxy, HTTP transport or shell command. API
method/path pairs are allowlisted, metadata model identifiers constrained. Generic
API and chat tools are absent.

All outbound HTTPS connections use DNS-pinned numeric addresses with original
hostname TLS/SNI/certificate verification. Every returned A/AAAA address must be
global/public; loopback, link-local, metadata, IPv6 ULA/special/mapped-private and
multicast are rejected. Proxies and implicit redirects are disabled. Explicit media
redirects repeat URL/address validation with a hop limit. Remote fetches are bounded
and streamed, including decoded response bytes. No media key is sent to public
media origins. The httpx/httpcore backend bridge relies on the frozen lockfile and
must be revalidated on updates.

KIE's own generation fetch cannot be DNS-pinned by this process, so input URLs are
limited to the fixed trusted `tempfile.redpandaai.co` host. External images are
first downloaded here and reuploaded. If KIE introduces another storage host,
review it explicitly; do not relax the policy to arbitrary remote URLs.

## Budgets, approvals and crash policy

BEGIN IMMEDIATE transactions cover budget checking/reserving, concurrent-task
counting and duplicate decisions in a shared WAL database. Integer micro-USD avoids
floating-point accumulation. Per-task/session/daily/lifetime limits and identical
stored policy prevent a new process raising the shared caps. Sessions/processes
have random IDs and clientInfo labels; the ledger is shared regardless of client.

Prepare returns an approval ID and full request digest. Execute refreshes metadata,
checks price against the reserved bound, binds the request/session, then atomically
claims before sending. Two processes cannot reserve the same remaining budget or
create duplicate active reservations. No automatic retry of paid submissions is
made; definite rejection releases liability, ambiguous/unknown sends retain it.
Only never-submitted reservations expire. Unresolved liabilities carry into later
days. Actual returned usage is recorded separately; absent reliable USD, estimates
remain conservative. Do not reset or delete the ledger to clear blocked spend.

Pricing is conservative: a narrow unconditional grammar and reviewed model-specific
prose profiles are recognised. Profiles match complete descriptions, exact allowed
input conditions and current live amounts; top-up discounts are ignored. Unsupported
fields/branches/tariffs return unknown pricing. Monetary rounding is upward.
Other unrecognised pricing blocks execution unless the owner writes an exact
request-specific, private, expiring quote. No tool can write that quote or submit a
self-reported price. The owner verifies its conservative bound. Tariff/provider
changes can exceed a local estimate, so separate provider-side hourly/daily/total
caps are mandatory operational policy. Owner controls model allowlists/IP policy.

## External clients and hard sandbox

The registrar and `kie-mcp-doctor` are owner-run CLIs, not MCP tools. Doctor is
offline and read-only; by default it does not read the key. `--check-secret` tests
loading without displaying it. It checks setup locations and values, not KIE key
validity, provider caps, existing ledger-policy agreement or OS isolation.
The supported runtime is POSIX macOS/Linux; use Linux paths and permissions in
WSL2. Native Windows and a ready-made container/hard sandbox are not implemented.

The registrar is an owner-run CLI, not an MCP tool. Preview is default, changes are
minimal and idempotent, differing entries rejected, backups private and created
before replacement. Do not run concurrent owner config editors/registrars: detection
before replacement narrows, but does not eliminate, the final OS-level race.

For strong isolation use a dedicated OS user/container with read-only runtime,
only allowed media/ledger mounts, media secret available solely to MCP, no SSH/home/
project-secrets/Docker socket and restricted egress. The untrusted agent must not
share writable access to owner config or ledger. Agent instructions reinforce the
policy but cannot stop a shell-enabled agent or serve as a security boundary.

## Remaining limitations

Live media-key generation/download and installed-MCP negative checks passed.
Codex session, Claude/Grok native CLI connectivity and Grok model-driven balance/docs
calls are verified. Claude model-driven invocation remains pending after a direct
launch OAuth 401 and KIE Fable/Sonnet chat-path 503 errors reproduced without MCP.
Chat-key model discovery passed; no login/provider settings were changed. This
points to a temporary KIE chat service/route issue rather than the media MCP.
KIE-side caps confirmation and final Phase 1 owner acceptance remain pending.
The local product-image scenario passed, including an explicitly
owner-authorized offline WebP conversion; the general MCP-only media rule remains
in effect for other operations. See the reports under `audit/`.
Only unified async media contracts are supported; external/recursive schema refs
are blocked. Friendly previews use declared fields and conservative aliases;
unsupported/ambiguous parameters and complex branches require low-level input.
Without an explicit model, all six friendly tools return a paginated metadata-only
comparison without uploads, media fetches or ledger mutation. User choice is the
default; cheapest selection among the first 20 candidates is explicit opt-in.
Image comparisons also work without a source, using a labelled one-image placeholder
for conditional pricing, never an executable approval. The read-only `kie_preflight`
reports operation/model requirements, missing inputs and parameter errors before
uploads or reservations. It does not open/verify local files or validate actual media
URLs; the existing upload, URL, budget and immutable-execution guards still apply.
Russian tool descriptions and approval summaries help explain actions; they do not
control client-owned approval buttons or add another approval/security boundary.
Quality descriptions are provider claims; no independent quality/speed scores exist.
With an explicit model, all six friendly tools have a dry-run preview without a
paid submission/reservation.
Local/external image previews can upload media to obtain an exact payload; trusted
KIE input URLs are reused and still checked by the URL/public-DNS guard.
Live previews and all six friendly paid flows passed after reviewed tariff profiles
were added; both Mini video modes, removal and upscale results were downloaded and
inspected. Historical Lite Internal Error and parallel-metadata 429 were followed
by an owner-authorized successful sequential pass; no failed paid task was retried.
Mini's promotional profile expires 2026-10-07 06:00 UTC. Account balance delta does
not match task-reported credit totals; billing-history attribution remains an owner
decision. See PRICE_SUPPORT.md and the final personal acceptance report.
The router currently checks task type/schema/price, not an independent quality/speed
score. Vault/cloud secret adapters, hard-sandbox deployment and SaaS webhook/queue/
object storage are later work. Do not represent these as complete or deployed.
