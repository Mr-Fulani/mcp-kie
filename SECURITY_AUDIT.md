# Security audit — secure-codex implementation

## Unknown-price risk opt-in (2026-10-05)

This is a later behavior change than the audit sections below. Unknown price still
returns `confidence=unknown`; a separate explicit user acknowledgement can now allow
preparation. The ledger reserves the configured per-task limit and binds the risk flag
to the immutable approval. This local reserve cannot limit KIE billing, which may be
higher. The historical audit conclusions below describe the revisions tested at their
dates; this addendum has not been live-acceptance tested.

## Portable local setup update (2026-10-04)

Owner-only bounded config/secret-file reads, strict config names/types, absolute
paths, validated numeric settings and an offline read-only doctor were added.
The separate `secret_file` source supports a local POSIX owner; it is plaintext,
not an encrypted vault or isolation from a same-user agent. Fresh frozen offline
installation and stdio launch with a fake private key passed on macOS/Python 3.14.2.
All 205 offline tests, Ruff and Bandit passed. Native Windows is unsupported; WSL2
needs a Linux client/filesystem and has no separate live acceptance. Older sections
below describe their original revision and environment. No real keys, paid tasks,
owner caps, client settings or existing ledgers were changed for this verification.
See [portable setup evidence](audit/portable-onboarding-2026-10-04.md).


## Repository / Original commit / Audit date

- Repository: https://github.com/gugu9999gu/KIE-MCP
- Original commit: `a79e8780838bb9f6fa1be8c3f6d21d6c19e2777d`
- Branch: `secure-codex`
- Audit date: 2026-10-03
- Status: local/offline verification passed; live acceptance incomplete
- Initial offline audit had no upstream push, paid generation or real client-config
  update. Subsequent authorized acceptance is recorded below; KIE-side policy
  has not been changed.

## Live acceptance update - 2026-10-03

Stages A-E passed: dedicated Keychain secret and protected roots/configuration,
installed Codex session, live schema/discovery/owner-quoted dry-run, one successful
`z-image` task with 0.8 actual credits and secure PNG download, and 15 installed-MCP
negative security checks with a clean stdout/stderr secret scan and unchanged ledger.
Claude Code now reports Connected; Grok Build's native doctor reports a healthy
stdio server and 22 discovered tools. Both registrations preserve unrelated client
settings and have private verified backups.

See `audit/phase1-stage-e-acceptance-2026-10-03.md` and
`audit/phase1-client-acceptance-2026-10-03.md`, plus the Stage A-D evidence.
The verification table below describes the original offline audit, not current
live status. The local product-image scenario subsequently passed: one Nano Banana
Edit task consumed 4 credits and its secure PNG download was converted offline to
lossless WebP under the owner's explicit exception. See
`audit/phase1-product-thiola-acceptance-2026-10-03.md`. KIE-side caps/model policy
confirmation, Claude model-driven invocation and final owner acceptance remain pending.
Grok's model-driven balance/docs calls passed on 2026-10-04 with one recovered
meta-tool argument error; no additional verification run occurred. Claude's chat
OAuth returned 401 before tool invocation and was deferred by the owner. See
`audit/phase1-grok-tool-invocation-2026-10-04.md` and
`audit/phase1-client-tool-invocation-2026-10-04.md`.

## Files inspected

Runtime files under `src/kie_mcp`: config, client, server, catalog, errors, webhook,
security, ledger, models, network, storage, service, launcher, registration and
package version. Reviewed pyproject/lockfile, license, workflow and regression tests.
The bundled documentation catalog is treated as an explicitly labelled fallback.

## Verification

| Check | Result |
|---|---|
| `pytest -q` on final implementation | 73 passed, no warnings |
| `ruff check .` | Passed |
| `git diff --check` | Passed including final documentation update |
| `bandit -r src` | Passed with four narrowly reviewed annotations |
| `pip-audit --local` after dependency fix | No known vulnerabilities |
| Real stdio initialize/list_tools | Passed with offline fake key |
| Mock prepare/execute/poll/download | Passed |
| Live DNS-pinned HTTPS docs fetch | Passed, 74,821 bytes |
| Configured-secret literal scan of project files | Passed, 0 matches |
| Separate media Keychain item | Unavailable or access denied |
| Live KIE balance/schema/price/generation | Not executed: media key unavailable |
| Actual Codex/Claude/Grok registration/connectivity | Pending |
| Owner KIE-side caps/key allowlists | Not verified or modified |

Final reports: `audit/bandit-accepted.json`, `audit/pip-audit-after.json`.
Earlier reports retain the original findings and intermediate scan history.
Dependency audit contains 65 records, including the local editable `kie-mcp`
package skipped because it is not a PyPI distribution. Local code is covered by
static review/tests, not by a public vulnerability database lookup.

## Dependencies

Frozen runtime/dev versions are recorded in `uv.lock`. No npx/latest execution.
Initial audit found two duplicate records for `PYSEC-2026-1845` in pytest 8.4.2.
After owner authorization, raised the pytest constraint to `>=9.0.3,<9.1` and
resolved 9.0.3. pytest-asyncio 0.26 explicitly required pytest<9; its bound was
updated for necessary compatibility and the lockfile resolves 1.4.0. No remaining
known advisories in the final installed dependency audit. The upstream CI matrix
has not been run remotely; it remains unchanged. Future database updates can reveal
new advisories; a clean scan is not a supply-chain guarantee.

Source advisory: https://github.com/pypa/advisory-database/blob/main/vulns/pytest/PYSEC-2026-1845.yaml

## Secrets / Authentication

`Settings.from_env` previously used the independent chat key. Now only the media
key is accepted; a matching chat/media key is rejected when the chat value is
available. Settings repr excludes the key. Startup fails without it.
The launcher reads only the dedicated Keychain item or Docker Secret and replaces
itself with a fixed child interpreter/module; key only in child env, chat key removed.
Owner config cannot contain secret fields. Keychain labels are constrained; stderr
and unexpected exceptions are suppressed. Tests cover key separation, argv, errors,
logs, representations and response object keys. No real key was stored in project.

## Filesystem access / Path traversal

`KieClient.upload_local_file` originally reopened a path after validation and relied
on extension MIME. A file or directory swap could redirect the read to a secret,
and a script renamed as an image could be uploaded. Fixed with canonical root
checks, traversal/suffix rejection, descriptor-relative no-follow traversal, fstat,
size checks and a bounded content-validated snapshot. A symlink-swap regression
proves the final open is blocked/detected. Base64 checks encoded and decoded limits.

Downloads use actual completed-task URLs and constrained task IDs, never caller
paths. `save_result` anchors output directory descriptors and publishes a fsynced
private file atomically using a no-replacement hard link. Tests cover escape, output
symlinks, size, generated names and separate non-overwritten results.

## Network access / SSRF

API and upload origins are fixed, method/path pairs constrained. Docs must use
HTTPS docs.kie.ai. No proxies, public MCP port, generic endpoint tool or chat tools.

`KieClient.upload_from_url` previously forwarded unchecked URLs to KIE, permitting
SSRF against the provider's private network. It now downloads public media locally
through `fetch_bytes` then validates and uploads bytes. `PinnedBackend` checks all
resolved A/AAAA addresses and connects directly to a checked IP, retaining original
TLS hostname verification. IPv4/IPv6 private/special/mapped addresses and multicast
are blocked; redirects are bounded and checked at every new connection. Remote
media is streamed under decoded byte limits. Tests verify mixed private DNS,
private redirect targets, numeric-IP pinning and IPv6 handling.

`KieService._validate_media_urls` restricts generation URLs to a trusted KIE upload
host because this process cannot pin DNS when KIE itself retrieves an input. Other
remote hosts must be ingested and reuploaded through MCP. This intentionally fails
closed for new storage hosts until explicitly reviewed. Completed-task downloads now
also use an explicit `tempfile.redpandaai.co`/`file.kie.ai`/`tempfile.aiquickdraw.com`
storage allowlist, so a
provider response cannot turn the result downloader into a general public URL fetch;
redirects and DNS targets remain subject to the pinned HTTPS checks.

The owner explicitly authorized review of `tempfile.aiquickdraw.com` on 2026-10-03
after a successful KIE task returned it. The review verified public DNS addresses
and a valid TLS hostname/chain before the exact host was added. Evidence:
`audit/phase1-stage-d-storage-host-review-2026-10-03.json`. Generation input URLs
remain restricted to `tempfile.redpandaai.co`.

## Command execution / Bandit findings

No eval, arbitrary shell command or agent-controlled executable is exposed.
The only process calls are required fixed Keychain retrieval and stdio replacement.
Initial Bandit findings were reviewed after owner authorization:

- B311, two retry jitter calls: replaced with `secrets.randbelow`; no finding remains.
- B608, budget SQL: originally concatenated only internal constants with bound values;
  rewritten as three fully static parameterised queries; no finding remains.
- B404: subprocess import exists solely for the fixed `/usr/bin/security` helper.
- B603: fixed helper argv, shell=False, constrained owner labels, no tool-supplied command.
- B606: fixed trusted interpreter and `kie_mcp.server`, secret passed only in env.
- B105: `KIE_SECRET_SOURCE="env"` is a mode selector, not a password.

The last four are narrowly annotated by their exact rule IDs with adjacent reasons.
No global rule exclusion or scanner bypass was configured. Bandit reports four
skipped individual tests and zero remaining findings. It can emit a benign warning
that the B105 annotation does not correspond to a failed test under that formatting.
These accepted annotations do not imply that arbitrary subprocess calls are safe.

## Logging

`_safe_call` originally exposed raw exceptions and `KieClient.request` raw errors.
A provider could echo credentials through message/details/object keys. Runtime
redaction now covers values and keys, including snake_case and camelCase credential
names, bearer headers, configured secret environment values and sensitive paths.
Unexpected errors use fixed text. JSON Schema errors do not echo private inputs.
Allowed output paths remain visible so users can find files.
No raw prompts/base64/private-file logging is implemented. Ledger stores hashes.

## Financial risk findings / Changes made

Original `kie_api_request`, chat tools and direct task creation could bypass spend
controls. Removed exposed generic/chat tools and added a client allowlist. Paid
requests are reachable from the MCP only through KieService prepare/execute.

SQLite WAL/BEGIN IMMEDIATE now cover reservations, shared budgets and duplicates.
Each process/session has an ID and safe clientInfo labels. Request digest/session/
TTL and fresh schema/price checks bind execution to preparation. Daily and lifetime
policy cannot be raised by another process. Unknown tariffs require an explicit
owner-configured exact-input quote; no client-supplied price is accepted. Dry-run
does not create a ledger/reservation or submit. Ambiguous paid requests are never
retried; unknown liabilities survive expiration. Actual usage is kept separately.

Regression tests include two-process remaining-budget and identical-fingerprint
races, stale preparations, unknown submissions, policy mismatch, digest mismatch,
idempotent paid calls, dry-run, business-code rejection inside HTTP 200 and no retry
of ambiguous sends. Client registration tests preserve providers and backups and
verify idempotency. Actual Grok table format was verified in a temporary project.

## Remaining risks / Acceptance work

1. The dedicated media key, protected roots, live balance/discovery/dry-run,
   one cheap generation/download and installed security refusals passed. Owner
   confirmation of KIE-side hourly/daily/total caps and key model policy remains
   outstanding, along with final acceptance. The local product-image scenario passed.
2. Actual registrations and native CLI connectivity are verified for all three
   clients. Grok model-driven balance/docs calls passed; Claude invocation remains
   pending after the direct-launch OAuth failure and KIE Fable/Sonnet 503/server_error
   retries reproduced by minimal chat requests without MCP. Independent chat-key
   model discovery passed; no provider/key changes are indicated by this evidence.
   The two-model comparison points to a temporary KIE chat service/route issue. See
   `audit/phase1-claude-kie-diagnosis-2026-10-04.md`. Existing
   providers/defaults/aliases were preserved. Registrar does not fully eliminate
   a race with a simultaneous unrelated OS-level config editor.
3. Free-text tariffs are parsed conservatively; complex/conditional or unrecognised
   prices require an exact-input owner quote. Provider overcharging or tariff changes
   can exceed an estimate; KIE-side caps are a required independent hard stop.
4. Unknown submitted tasks require owner/provider-history reconciliation. Do not
   clear spend history by deleting a ledger. Owner policy migration is deliberate.
5. Friendly routing handles declared aliases, string duration and required primary
   images, exposes dry-run/model_input, and compares known prices. 88 focused checks
   passed initially; after owner-authorized tariff remediation, 136 focused checks
   and all selected live friendly previews passed on 2026-10-04. Reviewed profiles
   parse fresh prices for selected personal models; unrecognised conditions still
   require owner quotes. Deprecated defaults are not implicitly applied. First paid
   Seedance Lite task failed at KIE; owner then authorized Mini and a sequential pass:
   all six friendly tools and both video modes completed/downloaded successfully.
   Promotion expiry and unassigned account-balance changes are documented in
   `audit/personal-final-acceptance-2026-10-04.md`. Quality/
   speed scoring and complex oneOf mapping remain later work. See
   `audit/personal-friendly-acceptance-2026-10-04.md`.
6. Magic signatures are not full decoding/antivirus/privacy enforcement. Owner must
   protect root/config/ledger ancestors; same-user shell-enabled agents are outside
   the complete enforcement boundary. Hard sandbox path is documented, not deployed.
7. The frozen httpx/httpcore network adapter relies on an internal bridge; revalidate
   on package upgrades. New storage/API families require explicit security review.
8. Only unified async media is supported. Vault/cloud adapters, FastAPI/webhook/queue
   deployment and permanent S3/R2/MinIO storage remain later phases; not claimed done.

README contains launch, separate install/uninstall/verify instructions, cost gates,
owner quote examples, failure handling and limits. SECURITY.md documents the full
boundary. AGENTS.md, CLAUDE.md and a Grok instruction example reinforce MCP-only
media usage, while explicitly not claiming those texts are a security boundary.
