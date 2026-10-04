# Portable owner setup acceptance

Verified on macOS with Python 3.14.2 on 2026-10-04. No real credential, KIE request
or paid task was used. No existing owner/client config or usage ledger was changed.

The documentation now starts with a developer's own checkout, media key, private
owner settings and dedicated media roots. Installation uses the committed lockfile.
macOS Keychain and Linux/WSL2 private-file examples are separate; the guide covers
client registration, model choice, exact preview and immutable paid approval.
Account-specific acceptance history is linked as evidence rather than setup policy.

Code adds an owner-run offline doctor and a plaintext secret-file source with
owner UID, exact private mode, regular-file, size and final-symlink guards. Config
reads use the same bounded descriptor guard. Unknown sections/names/types, an
explicit missing config, relative filesystem paths and invalid numeric settings
are rejected. Diagnostics never display a key or configuration values. A plaintext
file does not encrypt a key or protect it from a same-user shell-enabled agent.

Verification:

- `uv sync --frozen --offline --no-dev` installed 31 packages, including this project, into
  an independent temporary virtual environment from the local cache. The existing
  development environment and lockfile were unchanged.
- The newly installed `kie-mcp-doctor --check-secret --json` loaded a fake owner-only
  key without displaying it. No network was used and no ledger was created.
- The newly installed launcher started from an unrelated working directory with
  that separate owner TOML, completed stdio initialization and exposed 23 tools.
  Private fixture files were unchanged; no media operation was called.
- All 205 offline tests passed, including 26 onboarding tests. Ruff, Bandit and
  whitespace checks passed; documentation links/fences and TOML examples parsed.
  The initial home-expansion fixture was corrected for `~`/`~/` behavior before
  the successful final run.

Linux is the POSIX configuration path, not an additional live run in this report.
WSL2 requires the client and private files in Linux; native Windows and a prepared
container deployment remain unsupported. Doctor does not validate KIE auth/caps or
existing ledger-policy agreement. The upstream CI installation still uses pip;
no remote CI or dependency audit was rerun or changed for this revision.

Structured smoke evidence: [portable-onboarding-2026-10-04.json](portable-onboarding-2026-10-04.json).
