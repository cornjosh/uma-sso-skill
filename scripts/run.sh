#!/usr/bin/env bash
set -euo pipefail

skill_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
umasso_bin="$skill_dir/assets/umasso"
bridge="$skill_dir/scripts/uma_sso_bridge.py"

if [[ "$(uname -s)" != "Linux" ]]; then
    printf '%s\n' '错误：官方 umasso 只支持 Linux/WSL。' >&2
    exit 2
fi
case "$(uname -m)" in
    x86_64|amd64) ;;
    *)
        printf '错误：官方 umasso 需要 x86_64/amd64，当前架构是 %s。\n' "$(uname -m)" >&2
        exit 2
        ;;
esac
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' '错误：缺少 python3。' >&2
    exit 2
fi
if [[ ! -x "$umasso_bin" ]]; then
    printf '错误：内置 umasso 不存在或不可执行：%s\n' "$umasso_bin" >&2
    exit 2
fi

umask 077
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$bridge" --umasso "$umasso_bin" "$@"
