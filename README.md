# UMA SSO Skill

Keep a Huawei UMA tunnel running in the background while AI agents reuse its SSH configuration for SSH, SCP, and SFTP access.

---

[简体中文版](README_CN.md)

---

## Features ✨

- Separates the background UMA bridge from foreground SSH sessions
- Reuses one tunnel across repeated SSH, SCP, and SFTP operations
- Generates and validates managed OpenSSH configurations
- Installs as an agent skill with an optional `uma` shell function

## Compatibility 🖥️

- Linux or WSL
- Bash and Python 3
- Current release: x86_64/amd64
- A valid Huawei UMA `sso://` or `umasso://` access URL

For copyright reasons, replace `assets/umasso` with the official Huawei UMA executable you downloaded and are authorized to use; the current file is an evaluation build. For aarch64 or another architecture, use the corresponding official executable and update the architecture check in `scripts/run.sh` accordingly.

## Installation 🚀

### Skills CLI

```bash
npx skills add cornjosh/uma-sso-skill
```

### Ask an agent to install it

Send this prompt to Codex, Claude Code, OpenCode, or another agent that supports skills:

```text
Read https://github.com/cornjosh/uma-sso-skill and install it as an agent skill for this environment.
```

### Use `uma` directly from your shell

After installing the skill, ask your agent to read its shell installation guide if you want to run `uma` directly from your shell:

```text
Follow references/install-shell.md from the uma-sso skill to install the uma command for my current shell.
```

## Get an SSO URL 🔑

1. Sign in to the Huawei UMA web portal.
2. Open **Operations → Assets → Access** and find the asset you want to access over SSH.
3. Press `F12` to open the browser developer tools, then select the **Network** tab.
4. Select the appropriate account, `SSH`, password, **Do not use a remote client**, and **Local operations**, then click **Log in**.
5. In the Network requests, copy the access URL that begins with `sso://`.

## Usage ⌨️

Send the URL beginning with `sso://` directly to your AI agent:

```bash
'sso://...'
```

Review [SKILL.md](SKILL.md) for the complete workflow and safety guidance before connecting.

## How it works 🔧

```text
Background terminal: UMA bridge
    └── Maintains the tunnel and generates an SSH config

Foreground terminals: SSH / SCP / SFTP
    └── Reuse the same config and may exit or reconnect independently
```

## Project structure 📦

```text
SKILL.md                    Agent instructions
scripts/run.sh              Unified entry point
scripts/uma_sso_bridge.py   UMA bridge manager
references/install-shell.md Shell function installation
assets/umasso               Replaceable official Huawei UMA executable
LICENSE                     BSD-3-Clause license text
NOTICE                      License scope and UMA executable exclusion
```

---

🏵 UMA SSO Skill © Josh Zeng. Released under the [BSD-3-Clause License](LICENSE), excluding `assets/umasso`; see [NOTICE](NOTICE).

Authored and maintained by Josh Zeng.

[@GitHub](https://github.com/cornjosh)
