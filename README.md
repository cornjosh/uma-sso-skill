# UMA SSO Skill

An agent skill for running Huawei UMA as a persistent background bridge while reusing its generated OpenSSH configuration from SSH, SCP, and SFTP sessions.

## Install

Install with the open agent skills CLI:

```bash
npx skills add cornjosh/uma-sso-skill
```

For a global Codex installation:

```bash
npx skills add cornjosh/uma-sso-skill -g -a codex
```

The repository contains one skill at its root, named `uma-sso`. Private repository installation requires GitHub authentication in the current environment.

## Requirements

- Linux or WSL on x86_64/amd64
- Bash and Python 3
- Access to a valid Huawei UMA `sso://` or `umasso://` link

The bundled `assets/umasso` is a 64-bit Huawei UMA executable. This repository does not grant separate redistribution rights for that binary; keep the repository private unless you have confirmed those rights.

## Use

Ask the agent to use `uma-sso`, or run the bridge directly from the installed skill:

```bash
scripts/run.sh 'sso://...'
scripts/run.sh -F N
```

The SSO link is secret and single-use. The official binary writes the complete link to `~/.usm/sso/log`; review [SKILL.md](SKILL.md) before connecting.

To expose an `uma` shell function, follow [references/install-shell.md](references/install-shell.md).
