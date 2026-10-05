# Secure KIE MCP

[![CI](https://github.com/Mr-Fulani/mcp-kie/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Mr-Fulani/mcp-kie/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

A local **stdio MCP server** for creating and editing media with your own KIE account.
Choose a model, inspect its parameters and price, approve one immutable request, then
wait and save the result. Paid submissions are never retried automatically.

Project repository: **[Mr-Fulani/mcp-kie](https://github.com/Mr-Fulani/mcp-kie)**.
[Installation guide](GETTING_STARTED.md) · [Шпаргалка команд](CHEATSHEET.md) ·
[Security boundary](SECURITY.md) · [Contributing](CONTRIBUTING.md).
MIT license; inherited attribution is preserved in [NOTICE.md](NOTICE.md).

## What is supported

| Capability | Current support |
|---|---|
| Image generation/editing, product photos, background removal, upscale | Six friendly tools; selected models tested on live KIE |
| Text-to-video, image-to-video and declared video-input models | Friendly `generate_video`; duration-aware comparison and Video-to-Video/reference inputs when the live schema supports them |
| Audio | Compatible unified async contracts through low-level tools; no dedicated friendly audio command or live audio acceptance |
| Model choice | Live catalog/schema/price comparison, pagination and explicit user choice |
| Results | Local files with readable date/label/type/model/task folders; existing folders untouched |
| Clients | Local stdio registration for Codex, Claude Code and Grok Build |
| Runtime | Python 3.11+, macOS/Linux POSIX; on Windows use WSL2 with Linux paths/permissions |

Native Windows, public HTTP MCP, video timeline editing, format conversion and a
multi-user SaaS backend are not implemented. WSL2 uses the Linux path; it has not
had a separate live acceptance run. Historical tests are evidence for their tested
models/settings, not a guarantee that every KIE model works today.

## Install and configure

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then clone:

```sh
git clone https://github.com/Mr-Fulani/mcp-kie.git
cd mcp-kie
```

 Use the committed lockfile:

```sh
uv sync --frozen
```

You need **one separate KIE media API key**. A KIE chat key, OpenAI key or Anthropic
key is not required by this server. Your MCP client has its own independent login.
Never paste the media key into chat, terminal command arguments or client JSON/TOML.

1. Create dedicated directories outside the checkout for uploads, results and the
   ledger, plus `~/.config/kie-mcp` (private directory, mode 0700).
2. Review `examples/owner-config.toml` on macOS or
   `examples/owner-config-linux.toml` on Linux/WSL2. Save your edited copy as
   `~/.config/kie-mcp/config.toml`, mode 0600. Use absolute paths or `~`, and choose
   your spending limits **before the first paid request**. Do not overwrite an
   existing owner's configuration.
3. On **macOS**, create a generic-password item in Keychain Access UI: service/name
   `kie-mcp-media`, account `media`, password = your separate media key.
   On **Linux/WSL2**, the example uses `secret_file`: save only your key in
   `~/.config/kie-mcp/media.key`, owned by you with mode 0600/0400, outside uploads,
   results and Git. Enter it through an editor; it is plaintext on disk, not a vault.
   Protect its directory and disk. Docker Secret is another supported source at
   the fixed `/run/secrets/KIE_MCP_API_KEY` mount; no ready-made container deployment
   is included. `env` is an explicit development fallback. `.env` is not auto-loaded.
4. Run the offline checker:

```sh
.venv/bin/kie-mcp-doctor
.venv/bin/kie-mcp-doctor --check-secret
```

The checker never uses the network or writes files/config/ledger. Default mode
never reads the key; `--check-secret` tests secret loading without displaying it
(Keychain may ask for access). PASS does not validate the key with KIE or confirm
provider-side caps. Follow with a read-only `kie_get_credits` call from your client.

Full walkthrough, first task and troubleshooting:
[Руководство установки и применения](GETTING_STARTED.md).

## Connect an MCP client

The registrar previews changes first, backs up before applying, preserves other
settings and refuses to overwrite a differing registration. Replace the example
with your **absolute** launcher path; no key goes into client configuration.

```sh
.venv/bin/kie-mcp-register codex --command /absolute/checkout/.venv/bin/kie-mcp-launch
# Review the preview, then:
.venv/bin/kie-mcp-register codex --command /absolute/checkout/.venv/bin/kie-mcp-launch --apply
```

Replace `codex` with `claude` or `grok`. Registration uses `~/.codex/config.toml`,
`~/.claude.json` or `~/.grok/config.toml` respectively. Restart the client and inspect
its tool list: 23 tools, including `kie_compare_models`. For another stdio client,
configure the launcher as its command with empty args; keep secrets in the launcher
source, not the client config. A launcher started alone waits for MCP messages.

To remove only this registration, use the same client/command with `--remove --apply`.
See the [client instructions template](examples/AGENT_INSTRUCTIONS.md) and official
[Codex MCP documentation](https://developers.openai.com/codex/mcp/).

## Use it

Ask: “Compare suitable KIE models for a product photo. Show supported resolution,
format and price. Wait for my model choice before preparing the task.”

Without `model`, all six friendly commands return choices without uploading media,
reserving money or generating anything. `kie_compare_models` offers search and
pagination (five entries by default, at most ten per page). Each call fetches live
catalog/schema/pricing; it does not reuse a stale local list. Provider descriptions
are claims, not measured quality ratings; generation speed remains unknown.

For video, the MCP reads an explicit `duration` parameter in seconds or one
unambiguous length in seconds or minutes from the prompt, then reports each candidate
as `supported`, `unsupported`, `uncertain` or `automatic` with the schema or provider
description that supplies the limit. `automatic` means the model chooses the output
length, so exact seconds are not guaranteed. Use `next_cursor` to review all catalog
pages. Unclear limits are not counted as confirmed matches. `input_type="video"`
searches Video-to-Video and declared video reference inputs; rows show `task_types`,
`is_video_to_video_model` and `video_input_semantics` to distinguish those categories.
A model can be catalogued as Video-to-Video and still expose a reference-video field;
that field can guide generation without guaranteeing frame-accurate editing.
Supply `video_path`/`video_url` to prepare a selected model.
For combined input/output limits, `input_video_duration_seconds` is a user estimate;
the MCP does not measure the clip locally.

With the chosen `model`, use `dry_run=true` for an exact preview. Image previews can
upload your source to KIE; video previews can upload the clip. Metadata-only comparison
does not upload media. Extra declared fields use `model_input`. Unknown or conditional
prices outside reviewed profiles stay unknown; they are never treated as free. After
the MCP warning, the user may explicitly accept that risk; the local ledger reserves
the configured per-task limit, while KIE may charge more. Explicit `auto_select=true` delegates
cheapest known-price selection among the first 20 candidates, not best quality.
After completion, the MCP reports actual USD only if KIE returns `costUsd`; otherwise
the final charge remains unknown and must not be inferred from credits or balance changes.

The paid path is `preview → prepare → execute → wait/get_task → download`.
`kie_prepare_task` reserves shared budget; `kie_execute_task` needs the approval ID
and unchanged model/input in the **same MCP process/session**. Execution rechecks
schema/price. A timeout/unknown submission is not rejection: keep the liability and
reconcile provider history before considering a retry.

`kie_download_result(task_id=..., result_label="studio-photo")` saves completed
results inside the configured root:
`YYYY-MM-DD__studio-photo__image__provider-model__FULL_TASK_ID/<random-name>.<actual-extension>`.
The label is optional, limited to 48 UTF-8 bytes, letters/digits/spaces/underscores/
hyphens; it cannot be a path. Date is task creation in UTC, falling back to current
UTC. Actual bytes determine type/extension. The response returns `output_path` and
`output_folder`. Old directories are not renamed; re-downloads create new files.

## Safety and limits

Defaults are $1/task, $5/session, $10/UTC day, $100 total and five concurrent tasks.
Review owner settings before use. All processes share one SQLite ledger and must
use identical stored budget policy. Do not delete/reset it or change its path to
bypass spend; budget changes require deliberate owner reconciliation. Limits are
conservative estimates, not a promise about provider charges. Confirm KIE-side
spending caps/model policy separately, especially before unattended operation.

Uploads/downloads are disabled without explicit roots. Media signatures, bounded
reads, anchored filesystem operations, fixed endpoints, HTTPS/public DNS pinning,
redirect checks and approval/budget guards apply. Unknown prices need an owner's
private exact-input quote or an explicit per-request user acknowledgement of the
unknown-price risk. The latter reserves the configured per-task limit locally;
actual KIE charges can be higher. Agents must explain this before setting
`accept_unknown_price=true`. No MCP tool manages keys, caps, roots or policy.

An agent with shell/network access under the **same OS account** can operate outside
MCP. This server does not isolate that agent or encrypt a plaintext secret file.
For stronger isolation use a dedicated OS user/container with protected config and
ledger, restricted mounts/egress and a key available only to MCP. See
[SECURITY.md](SECURITY.md) for the full boundary and current limitations.

## Development and status

See [CONTRIBUTING.md](CONTRIBUTING.md) for locked installation, offline checks and
secret-safe contributions. No paid acceptance is required for ordinary local tests.

- [PERSONAL_USE.md](PERSONAL_USE.md): tested personal workflows and remaining limitations.
- [PRICE_SUPPORT.md](PRICE_SUPPORT.md): reviewed tariff profiles and expiry conditions.
- [SAAS_READINESS.md](SAAS_READINESS.md): work needed for a multi-user backend.
- [SECURITY_AUDIT.md](SECURITY_AUDIT.md), `audit/`: historical verification evidence.

Published reports are privacy-redacted historical evidence: live media links,
private prompts, owner paths and raw diagnostic outputs are omitted.
Reports describe the original test account/environment, not settings to copy or
requirements to log into the original owner's account. Your installation uses your
own keys, private files, budget policy and MCP client identity.
