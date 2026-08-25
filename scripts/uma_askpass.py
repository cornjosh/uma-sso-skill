#!/usr/bin/env python3
"""Minimal SSH_ASKPASS helper backed by a private temporary password file."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> int:
    prompt = " ".join(sys.argv[1:]).casefold()
    accepted = ("password", "passcode", "密码", "口令")
    if not any(word in prompt for word in accepted):
        return 1
    password_file = os.environ.get("UMA_SSO_PASSWORD_FILE", "")
    if not password_file:
        return 1
    try:
        password = Path(password_file).read_text(encoding="utf-8")
    except OSError:
        return 1
    sys.stdout.write(password)
    if not password.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
