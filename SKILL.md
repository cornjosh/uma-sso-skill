---
name: uma-sso
description: Manage Huawei UMA background tunnels and clients whenever a request mentions UMA, an sso:// or umasso:// link, UMA SSO login, UMA bridge, SSH/SCP through UMA, or generated_ssh_config. Bundles the Linux x86_64 UMA binary and creates managed OpenSSH configurations for separate background terminals.
metadata:
  short-description: "UMA sso:// umasso:// background tunnel manager"
---

# UMA SSO background access

Use `scripts/run.sh` on Linux/WSL x86_64. Managed configs live at `/tmp/uma/.config/generated_ssh_config_N`.

For a persistent `uma` shell function, read [references/install-shell.md](references/install-shell.md) only when the user asks to configure their shell.

## Operation

Treat the UMA bridge and foreground clients as independent layers. Start the bridge once in a long-lived background terminal; it maintains the tunnel and config but does not run SSH. Wait for `UMA_BRIDGE_READY=N` and retain both `N` and the bridge's tool session ID:

```bash
scripts/run.sh 'sso://...'
```

Run SSH, SCP, or SFTP in separate foreground terminals and reuse `N`:

```bash
scripts/run.sh -F N
scripts/run.sh -S -F N ./local-file :/remote/path
scripts/run.sh -C sftp -F N
```

Clients may exit and reconnect without restarting the bridge. If `N` is unknown, `scripts/run.sh -F` removes invalid configs and prompts among reachable ones; `-F N` validates only that tunnel.

`-C ssh|scp|sftp` adds the OpenSSH config automatically. Other executables receive arguments after `--`; use `{config}`, `{alias}`, `{host}`, `{port}`, or `{user}`. Matching `UMA_SSH_*` variables and private AskPass state are also exported.

## Recovery

- An SSO link is a single-use secret. Consume it once and reuse the resulting **bridge/config**, never the link. `authenticate failed` requires a fresh user-provided link; do not retry the old one.
- SSH exit, tool interruption, or one empty poll does not prove UMA failed. Continue polling a running client through its existing tool session ID with empty input.
- Reconnect a client only after an exit code, EOF, `connection closed`, or failed `-F N` validation. A live bridge/config needs no new link.
- After interruption, check bridge session, config reachability, existing client session, and remote command/file state—in that order. Remote work may have completed, stopped, or remained running; inspect before repeating it.
- Only a stopped bridge or unreachable/expired config requires a new bridge and fresh link.

Keep interactive PTY commands short. For complex logic, upload a local script through the same bridge. Trust meaningful output and exit status, not wrapped or ANSI-corrupted command echo.

For large or important transfers, upload a checksum, verify it remotely before use, and inspect the remote size/checksum after interruption. Retrying SCP may be necessary; restarting UMA is not.

## Safety and cleanup

- Never echo, persist, or log a link yourself. Never read or expose password sidecars, or pass them to an external program unless the user explicitly trusts it.
- A link argument is visible in process listings and possibly shell history. If not supplied inline, run without it and use the no-echo prompt.
- Before launching, disclose that the official binary writes the full link to `~/.usm/sso/log`.
- The bridge temporarily replaces `~/.usm/sso/SSOProfile.ini` and restores it after capture or abnormal cleanup.
- Tunnel access does not authorize remote commands or transfers; observe the active environment's permissions.
- Stop clients first, then the bridge with Ctrl-C; cleanup removes its config and sidecar.
- If the bridge exits before `UMA_BRIDGE_READY`, report the failure without exposing credentials.
