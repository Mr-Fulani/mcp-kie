# Contributing and local development

Use Python 3.11+ on macOS/Linux (or Linux inside WSL2). Start from a reviewed revision
of this standalone repository. Install committed dependencies without upgrading them:

```sh
uv sync --frozen --extra dev
.venv/bin/ruff check src tests
.venv/bin/pytest -q
.venv/bin/bandit -q -r src/kie_mcp
```

These tests use mock HTTP, temporary roots and fake media keys. They need no real
KIE credentials, network access or paid generation. The onboarding test starts a
fresh stdio launcher with its own private fixture config/secret, lists tools and
checks that no usage database is created. The doctor also has a module entry:
`.venv/bin/python -m kie_mcp.doctor`.

For your own media work follow [GETTING_STARTED.md](GETTING_STARTED.md). Keep secrets,
owner config, quotes, media and the real ledger outside the checkout. `.gitignore`
is a secondary precaution; never rely on it to make publishing a credential safe.
Do not paste credentials into issues, logs, test snapshots, shell commands or PRs.
Report suspected security issues privately to the repository maintainer through
an available private channel; no dedicated security contact is configured here.

Do not run scripts under historical `audit/` or temporary acceptance harnesses as
a test suite. Some live harnesses submit paid work and must not be repeated after
an ambiguous submission. Real acceptance needs a separate key, owner caps, one
reviewed immutable request and secure MCP prepare/execute/download.

For changes affecting money, secrets, filesystem or network contracts, include
focused negative tests. Preserve fail-closed unknown prices, fixed endpoints,
DNS/TLS guards, owner policy separation and no automatic paid POST retries.
New model pricing profiles must match complete live descriptions and declared
conditions; include source/date/expiry fixtures, never a guessed credit conversion.
Do not solve failures by deleting ledgers or removing safety gates.

Document changes to tool defaults, arguments and owner settings in README, the
setup guide and SECURITY.md. Keep account-specific history in `audit/` rather than
presenting it as required setup. Do not commit personal client configurations.
Native Windows, standalone container deployment and SaaS isolation are separate
work; do not claim they are tested because POSIX offline tests passed.

No dependency or CI upgrades are required for the setup improvements. The current
upstream CI workflow uses pip rather than the frozen uv install used above; align
that separately with maintainer approval. Do not present a local run as remote CI.
