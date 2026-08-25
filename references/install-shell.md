# Install a shell shortcut

Read this only when the user asks to make UMA available directly from their shell.

With permission to edit the user's shell startup file, add this managed block to `~/.bashrc` (or the equivalent file for their shell):

```bash
# >>> uma-sso >>>
uma() {
    bash "$HOME/.agents/skills/uma-sso/scripts/run.sh" "$@"
}
# <<< uma-sso <<<
```

Verify the referenced `run.sh` exists first. If the skill is installed elsewhere, substitute its actual absolute path. Do not duplicate the block; update the existing managed block when present. Reload with `source ~/.bashrc` or start a new shell, then use `uma` exactly like `scripts/run.sh`:

```bash
uma 'sso://...'
uma -F N
uma -S -F N ./local-file :/remote/path
```

If appending through a quoted heredoc, the trailing `EOF` closes the heredoc and is not written into the startup file.
