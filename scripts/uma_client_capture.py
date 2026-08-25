#!/usr/bin/env python3
"""Capture the PuTTY-style connection arguments emitted by umasso."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time


def parse_putty_args(arguments: list[str]) -> dict[str, object]:
    result: dict[str, object] = {"host": "", "port": 22, "user": "", "password": ""}
    value_options = {"-P": "port", "-l": "user", "-pw": "password"}
    index = 0
    expect_host = False
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-ssh":
            expect_host = True
            index += 1
            continue
        if argument in value_options and index + 1 < len(arguments):
            result[value_options[argument]] = arguments[index + 1]
            index += 2
            continue
        matched = False
        for option, field in value_options.items():
            prefix = option + "="
            if argument.startswith(prefix):
                result[field] = argument[len(prefix) :]
                matched = True
                break
        if matched:
            index += 1
            continue
        if expect_host and not argument.startswith("-"):
            result["host"] = argument
            expect_host = False
        elif not result["host"] and not argument.startswith("-"):
            result["host"] = argument
        index += 1

    try:
        result["port"] = int(str(result["port"]), 10)
    except ValueError:
        result["port"] = 0
    result["capture_pid"] = os.getpid()
    return result


def write_capture(path: Path, data: dict[str, object]) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False)
            output.write("\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    capture_file = os.environ.get("UMA_SSO_CAPTURE_FILE", "")
    if not capture_file or not os.path.isabs(capture_file):
        return 2
    write_capture(Path(capture_file), parse_putty_args(sys.argv[1:]))

    def stop(*_: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    raise SystemExit(main())
