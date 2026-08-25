#!/usr/bin/env python3
"""Launch Huawei UMA, discover its local SSH listener, and emit ssh_config."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

from sso_to_ssh import SSOParseError, parse_sso, read_link, render_config, safe_alias


CONFIG_NAME = "generated_ssh_config_"
PASSWORD_NAME = "generated_ssh_password_"


@dataclass(frozen=True)
class StoredConfig:
    number: int
    path: Path
    alias: str
    host: str
    port: int
    user: str


def config_directory() -> Path:
    """Return the private generated-config directory (overridable for tests)."""
    configured = os.environ.get("UMA_CONFIG_DIR")
    directory = Path(configured).expanduser() if configured else Path("/tmp/uma/.config")
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise SSOParseError(f"配置目录不是安全的普通目录：{directory}")
        stat = directory.stat()
        if stat.st_uid != os.getuid():
            raise SSOParseError(f"配置目录不属于当前用户：{directory}")
        directory.chmod(0o700)
    except OSError as exc:
        raise SSOParseError(f"无法创建配置目录 {directory}: {exc}") from exc
    return directory


def reserve_config_path(directory: Path) -> tuple[int, Path]:
    """Atomically reserve the smallest currently unused config number."""
    number = 1
    while True:
        path = directory / f"{CONFIG_NAME}{number}"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            number += 1
            continue
        except OSError as exc:
            raise SSOParseError(f"无法保留 SSH 配置文件 {path}: {exc}") from exc
        os.close(descriptor)
        return number, path


def password_path(config: StoredConfig | Path) -> Path:
    path = config.path if isinstance(config, StoredConfig) else config
    suffix = path.name.removeprefix(CONFIG_NAME)
    return path.with_name(f"{PASSWORD_NAME}{suffix}")


def parse_stored_config(path: Path) -> StoredConfig:
    match = re.fullmatch(re.escape(CONFIG_NAME) + r"(\d+)", path.name)
    if not match:
        raise SSOParseError(f"不是受管理的 SSH 配置：{path}")
    try:
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise SSOParseError(f"拒绝读取不安全的 SSH 配置：{path}")
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SSOParseError(f"无法读取 SSH 配置 {path}: {exc}") from exc
    values: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) == 2 and parts[0].casefold() in {"host", "hostname", "port", "user"}:
            values.setdefault(parts[0].casefold(), parts[1].strip())
    try:
        host = str(ipaddress.ip_address(values["hostname"].strip("[]")))
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError
        port = int(values["port"], 10)
        if not 1 <= port <= 65535:
            raise ValueError
        alias, user = values["host"], values["user"]
        if not alias or not re.fullmatch(r"[A-Za-z0-9_.-]+", alias):
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_.@\\-]+", user):
            raise ValueError
    except (KeyError, ValueError) as exc:
        raise SSOParseError(f"SSH 配置内容无效：{path}") from exc
    return StoredConfig(int(match.group(1)), path, alias, host, port, user)


def config_is_alive(config: StoredConfig, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((config.host, config.port), timeout=timeout):
            return True
    except OSError:
        return False


def remove_stored_config(config: StoredConfig | Path) -> None:
    path = config.path if isinstance(config, StoredConfig) else config
    path.unlink(missing_ok=True)
    password_path(path).unlink(missing_ok=True)


def find_available_configs(directory: Path, requested: int | None) -> list[StoredConfig]:
    paths = (
        [directory / f"{CONFIG_NAME}{requested}"]
        if requested is not None
        else sorted(
            directory.glob(f"{CONFIG_NAME}*"),
            key=lambda item: int(item.name[len(CONFIG_NAME):])
            if item.name[len(CONFIG_NAME):].isdigit() else sys.maxsize,
        )
    )
    available: list[StoredConfig] = []
    for path in paths:
        if not path.exists():
            if requested is not None:
                raise SSOParseError(f"配置 {requested} 不存在：{path}")
            continue
        try:
            config = parse_stored_config(path)
        except SSOParseError:
            if requested is not None:
                raise
            remove_stored_config(path)
            print(f"已清理无效配置：{path.name}", file=sys.stderr)
            continue
        if not config_is_alive(config):
            remove_stored_config(config)
            print(f"已清理失效配置：{path.name}", file=sys.stderr)
            if requested is not None:
                raise SSOParseError(f"配置 {requested} 的 UMA 本地隧道已失效")
            continue
        available.append(config)
    return available


def find_umasso(requested: str | None) -> str:
    if requested:
        candidate = Path(requested).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise SSOParseError(f"umasso 不存在或不可执行：{candidate}")
        return str(candidate.resolve())
    located = shutil.which("umasso")
    if not located:
        raise SSOParseError("未找到 umasso；请先安装软件或使用 --umasso 指定程序路径")
    return located


def resolve_executable(requested: str | None, default: Path, label: str) -> str:
    candidate = Path(requested).expanduser() if requested else default
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise SSOParseError(f"{label} 不存在或不可执行：{candidate}")
    return str(candidate.resolve())


def write_private_text(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
        temporary.chmod(0o600)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def override_client_profile(profile: Path, capture_helper: str) -> tuple[bool, bytes, int]:
    """Temporarily make UMA invoke our PuTTY-argument capture helper."""
    try:
        if profile.is_symlink():
            raise SSOParseError(f"拒绝覆盖符号链接配置：{profile}")
        existed = profile.exists()
        original = profile.read_bytes() if existed else b""
        original_mode = profile.stat().st_mode & 0o777 if existed else 0o600
        content = (
            "[ssh]\n"
            "Name=putty\n"
            f"Path={capture_helper}\n"
            "Charset=UTF-8\n"
            "AuthMode=\n"
            "TerminalMode=\n"
        )
        write_private_text(profile, content)
        return existed, original, original_mode
    except OSError as exc:
        raise SSOParseError(f"无法临时设置 UMA 客户端配置 {profile}: {exc}") from exc


def restore_client_profile(profile: Path, backup: tuple[bool, bytes, int]) -> None:
    existed, original, original_mode = backup
    try:
        if existed:
            temporary = profile.with_name(profile.name + ".restore.tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, original_mode)
            with os.fdopen(descriptor, "wb") as output:
                output.write(original)
            temporary.chmod(original_mode)
            temporary.replace(profile)
        else:
            profile.unlink(missing_ok=True)
    except OSError as exc:
        raise SSOParseError(f"恢复 UMA 客户端配置失败 {profile}: {exc}") from exc


def wait_for_capture(
    process: subprocess.Popen[bytes], capture_file: Path, timeout: float
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if capture_file.exists():
            try:
                if capture_file.stat().st_size > 64 * 1024:
                    raise SSOParseError("UMA 客户端参数捕获文件异常过大")
                data = json.loads(capture_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SSOParseError(f"无法读取 UMA 客户端参数：{exc}") from exc
            if not isinstance(data, dict):
                raise SSOParseError("UMA 客户端参数格式无效")
            host = str(data.get("host", "")).strip().strip("[]")
            if host == "localhost":
                host = "127.0.0.1"
            try:
                address = ipaddress.ip_address(host)
            except ValueError as exc:
                raise SSOParseError(f"UMA 返回了无效的本地地址：{host!r}") from exc
            if not address.is_loopback:
                raise SSOParseError(f"拒绝使用 UMA 返回的非回环地址：{host}")
            try:
                port = int(data.get("port", 0))
            except (TypeError, ValueError) as exc:
                raise SSOParseError("UMA 返回了无效的本地端口") from exc
            if not 1 <= port <= 65535:
                raise SSOParseError("UMA 返回的本地端口超出范围")
            user = str(data.get("user", "")).strip()
            if user and not re.fullmatch(r"[A-Za-z0-9_.@\\-]+", user):
                raise SSOParseError("UMA 返回了无效的 SSH 用户名")
            return {
                "host": host,
                "port": port,
                "user": user,
                "password": str(data.get("password", "")),
                "capture_pid": int(data.get("capture_pid", 0)),
            }
        if process.poll() is not None:
            raise SSOParseError(f"umasso 在输出临时认证信息前退出，退出码 {process.returncode}")
        time.sleep(0.1)
    raise SSOParseError(f"在 {timeout:g} 秒内没有收到 UMA 临时认证信息")


def write_ssh_config(path: Path, content: str) -> None:
    try:
        write_private_text(path, content)
    except OSError as exc:
        raise SSOParseError(f"无法写入 SSH 配置 {path}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="维持华为 UMA 后台隧道，或使用受管配置启动 SSH/SCP/其他客户端。",
        add_help=False,
    )
    parser.add_argument("-H", "-h", "--help", action="help", help="显示帮助并退出")
    parser.add_argument(
        "-F", dest="stored_config", nargs="?", const="", metavar="N",
        help="检测并选择已生成配置；-F N 只使用编号 N",
    )
    parser.add_argument(
        "-S", "--scp", action="store_true",
        help="使用 scp 传输（等价于 -C scp）；远端端点可写为 :PATH",
    )
    parser.add_argument(
        "-C", "--client", metavar="PROGRAM",
        help="使用 ssh、scp、sftp 或其他外部客户端连接选中的 -F 配置",
    )
    parser.add_argument("--umasso", help="umasso 可执行文件路径，默认从 PATH 查找")
    parser.add_argument("--capture-helper", help="UMA 参数捕获助手路径")
    parser.add_argument("--askpass-helper", help="OpenSSH AskPass 助手路径")
    parser.add_argument("--alias", help="生成的 OpenSSH Host 别名")
    parser.add_argument("--ssh-config", help="将生成的 SSH 配置写入指定文件，而不是标准输出")
    parser.add_argument("--timeout", type=float, default=20.0, help="发现端口的等待秒数（默认 20）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--auto-connect", action="store_true",
        help="捕获后在同一进程启动客户端（仅为兼容，默认只维持后台隧道）",
    )
    mode.add_argument(
        "--verify-reuse", action="store_true",
        help="保持第一个 SSH 连接并验证临时密码能否建立第二个独立连接",
    )
    parser.add_argument(
        "arguments", nargs="*", metavar="ARG",
        help="可选的 sso:// 或 umasso:// 链接，以及客户端参数",
    )
    return parser


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def stop_pid(pid: int) -> None:
    if pid <= 1:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def verify_password_reuse(
    ssh_path: str,
    config_path: Path,
    alias: str,
    ssh_environment: dict[str, str],
    temporary_dir: Path,
) -> None:
    master_socket = temporary_dir / "reuse-master.sock"
    master = subprocess.run(
        [
            ssh_path, "-F", str(config_path), "-M", "-S", str(master_socket),
            "-N", "-f", alias,
        ],
        env=ssh_environment,
        text=True,
        capture_output=True,
    )
    if master.returncode != 0:
        detail = master.stderr.strip()[-800:]
        raise SSOParseError(f"第一次 SSH 认证失败：{detail or '无错误详情'}")

    try:
        check = subprocess.run(
            [ssh_path, "-F", str(config_path), "-S", str(master_socket), "-O", "check", alias],
            text=True,
            capture_output=True,
        )
        if check.returncode != 0:
            raise SSOParseError("第一个 SSH 主连接未能保持活动")

        second = subprocess.run(
            [
                ssh_path, "-F", str(config_path),
                "-o", "ControlMaster=no", "-o", "ControlPath=none",
                alias, "printf 'UMA_REUSE_OK\\n'; id -u",
            ],
            env=ssh_environment,
            text=True,
            capture_output=True,
        )
        if second.returncode != 0:
            detail = second.stderr.strip()[-800:]
            raise SSOParseError(
                "第二个独立 SSH 连接认证失败；临时密码不能在已有会话期间复用。"
                f"{': ' + detail if detail else ''}"
            )
        lines = second.stdout.splitlines()
        if "UMA_REUSE_OK" not in lines:
            raise SSOParseError("第二个 SSH 连接成功，但只读验证标记缺失")
        marker_index = lines.index("UMA_REUSE_OK")
        remote_uid = lines[marker_index + 1] if len(lines) > marker_index + 1 else "未知"
        print(
            "验证成功：第一个 SSH 会话保持期间，同一 UMA 临时密码成功建立了第二个独立连接。"
            f"远端 UID={remote_uid}。",
            file=sys.stderr,
        )
    finally:
        subprocess.run(
            [ssh_path, "-F", str(config_path), "-S", str(master_socket), "-O", "exit", alias],
            text=True,
            capture_output=True,
        )


def choose_config(configs: list[StoredConfig]) -> StoredConfig:
    if not configs:
        raise SSOParseError("没有可用的 UMA SSH 配置")
    if len(configs) == 1:
        config = configs[0]
        print(
            f"使用配置 {config.number}: {config.user}@{config.alias} "
            f"({config.host}:{config.port})",
            file=sys.stderr,
        )
        return config
    print("可用的 UMA SSH 配置：", file=sys.stderr)
    for config in configs:
        print(
            f"  [{config.number}] {config.user}@{config.alias} "
            f"({config.host}:{config.port})",
            file=sys.stderr,
        )
    try:
        selected = input("请输入配置编号后回车：").strip()
        number = int(selected, 10)
    except (EOFError, ValueError) as exc:
        raise SSOParseError("未输入有效的配置编号") from exc
    for config in configs:
        if config.number == number:
            return config
    raise SSOParseError(f"配置编号 {number} 不在可用列表中")


def ssh_environment_for(config: StoredConfig, askpass_helper: str) -> dict[str, str]:
    environment = os.environ.copy()
    secret = password_path(config)
    if secret.is_file():
        environment["SSH_ASKPASS"] = askpass_helper
        environment["SSH_ASKPASS_REQUIRE"] = "force"
        environment["UMA_SSO_PASSWORD_FILE"] = str(secret)
        environment.setdefault("DISPLAY", ":0")
    return environment


def expand_scp_arguments(arguments: list[str], alias: str) -> list[str]:
    if len(arguments) < 2:
        raise SSOParseError("-S 至少需要 scp 的源和目标参数")
    return [f"{alias}{item}" if item.startswith(":") else item for item in arguments]


def connect_with_config(
    config: StoredConfig,
    *,
    client_name: str,
    client_arguments: list[str],
    askpass_helper: str,
) -> int:
    if not client_name or client_name.startswith("-"):
        raise SSOParseError("客户端程序名无效")
    executable = shutil.which(client_name)
    if not executable:
        raise SSOParseError(f"未找到客户端 {client_name}")
    program = Path(executable).name.casefold()
    expanded = expand_client_arguments(client_arguments, config)
    if program == "scp":
        command = [
            executable, "-F", str(config.path),
            *expand_scp_arguments(expanded, config.alias),
        ]
    elif program == "ssh":
        command = [executable, "-F", str(config.path), config.alias, *expanded]
    elif program == "sftp":
        command = [executable, "-F", str(config.path), *expanded, config.alias]
    else:
        command = [executable, *expanded]
    print(
        f"正在启动客户端 {client_name}："
        f"{' '.join(shlex.quote(part) for part in command)}",
        file=sys.stderr,
    )
    environment = ssh_environment_for(config, askpass_helper)
    environment.update(
        {
            "UMA_SSH_CONFIG": str(config.path),
            "UMA_SSH_ALIAS": config.alias,
            "UMA_SSH_HOST": config.host,
            "UMA_SSH_PORT": str(config.port),
            "UMA_SSH_USER": config.user,
        }
    )
    return subprocess.call(command, env=environment)


def expand_client_arguments(arguments: list[str], config: StoredConfig) -> list[str]:
    replacements = {
        "{config}": str(config.path),
        "{alias}": config.alias,
        "{host}": config.host,
        "{port}": str(config.port),
        "{user}": config.user,
    }
    return [replacements.get(argument, argument) for argument in arguments]


def split_link(arguments: list[str]) -> tuple[str | None, list[str]]:
    links = [item for item in arguments if item.casefold().startswith(("sso://", "umasso://"))]
    if len(links) > 1:
        raise SSOParseError("一次只能提供一个 SSO 链接")
    link = links[0] if links else None
    remaining = arguments.copy()
    if link is not None:
        remaining.remove(link)
    return link, remaining


def main() -> int:
    args = build_parser().parse_args()
    if args.scp and args.client and args.client.casefold() != "scp":
        print("错误：-S 不能与非 scp 的 -C/--client 同时使用", file=sys.stderr)
        return 2
    if args.timeout <= 0 or args.timeout > 300:
        print("错误：--timeout 必须在 0-300 秒之间", file=sys.stderr)
        return 2

    process: subprocess.Popen[bytes] | None = None
    profile = Path.home() / ".usm" / "sso" / "SSOProfile.ini"
    profile_backup: tuple[bool, bytes, int] | None = None
    temporary_dir: Path | None = None
    generated_config: StoredConfig | None = None
    managed_config_path: Path | None = None
    capture_pid = 0
    try:
        link, client_arguments = split_link(args.arguments)
        script_dir = Path(__file__).resolve().parent
        askpass_helper = resolve_executable(
            args.askpass_helper, script_dir / "uma_askpass.py", "AskPass 助手"
        )

        if args.stored_config is not None:
            if link is not None:
                raise SSOParseError("-F 使用已有配置，不能同时提供 SSO 链接")
            requested: int | None = None
            if args.stored_config:
                try:
                    requested = int(args.stored_config, 10)
                except ValueError as exc:
                    raise SSOParseError("-F 后的配置编号必须是正整数") from exc
                if requested <= 0:
                    raise SSOParseError("-F 后的配置编号必须是正整数")
            selected = choose_config(find_available_configs(config_directory(), requested))
            client_name = args.client or ("scp" if args.scp else "ssh")
            result = connect_with_config(
                selected,
                client_name=client_name,
                client_arguments=client_arguments,
                askpass_helper=askpass_helper,
            )
            if result != 0:
                raise SSOParseError(f"{client_name} 退出，状态码 {result}")
            return 0

        if link is None:
            link = read_link().strip()
        connection = parse_sso(link)
        executable = find_umasso(args.umasso)
        alias = safe_alias(connection, args.alias)
        capture_helper = resolve_executable(
            args.capture_helper, script_dir / "uma_client_capture.py", "参数捕获助手"
        )

        runtime_base = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
        if not runtime_base.is_dir():
            runtime_base = Path("/tmp")
        temporary_dir = Path(tempfile.mkdtemp(prefix=f"uma-sso-{os.getuid()}-", dir=runtime_base))
        temporary_dir.chmod(0o700)
        capture_file = temporary_dir / "client.json"
        if args.ssh_config:
            config_path = Path(args.ssh_config).expanduser().resolve()
            config_number = -1
        else:
            config_number, config_path = reserve_config_path(config_directory())
            managed_config_path = config_path

        profile_backup = override_client_profile(profile, capture_helper)

        print(
            "警告：官方 umasso 会把完整 SSO 链接写入 ~/.usm/sso/log，"
            "且运行期间链接及临时密码可能出现在官方客户端的进程参数或日志中。",
            file=sys.stderr,
        )
        child_environment = os.environ.copy()
        child_environment["UMA_SSO_CAPTURE_FILE"] = str(capture_file)
        process = subprocess.Popen(
            [executable, link],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=child_environment,
        )
        captured = wait_for_capture(process, capture_file, args.timeout)
        capture_pid = int(captured["capture_pid"])
        restore_client_profile(profile, profile_backup)
        profile_backup = None
        capture_file.unlink(missing_ok=True)

        captured_user = str(captured["user"]) or connection.asset_user
        captured_connection = replace(connection, asset_user=captured_user)
        config = render_config(
            captured_connection,
            "local",
            alias,
            str(captured["host"]),
            int(captured["port"]),
        )
        config += (
            "    PreferredAuthentications keyboard-interactive,password\n"
            "    PubkeyAuthentication no\n"
            "    NumberOfPasswordPrompts 1\n"
            "    StrictHostKeyChecking accept-new\n"
        )
        write_ssh_config(config_path, config)
        if config_number >= 0:
            generated_config = parse_stored_config(config_path)
        password = str(captured["password"])
        print(
            f"已获得 UMA 本地 SSH 会话 {captured['host']}:{captured['port']}，"
            f"用户 {captured_user}；临时密码{'已捕获' if password else '未提供'}。",
            file=sys.stderr,
        )

        ssh_environment = os.environ.copy()
        if password:
            password_file = (
                password_path(generated_config)
                if generated_config is not None
                else temporary_dir / "password"
            )
            write_private_text(password_file, password)
            ssh_environment["SSH_ASKPASS"] = askpass_helper
            ssh_environment["SSH_ASKPASS_REQUIRE"] = "force"
            ssh_environment["UMA_SSO_PASSWORD_FILE"] = str(password_file)
            ssh_environment.setdefault("DISPLAY", ":0")

        if args.verify_reuse:
            if not password:
                raise SSOParseError("UMA 没有下发临时密码，无法执行密码复用验证")
            ssh_path = shutil.which("ssh")
            if not ssh_path:
                raise SSOParseError("未找到标准 OpenSSH 客户端 ssh")
            verify_password_reuse(ssh_path, config_path, alias, ssh_environment, temporary_dir)
            return 0

        if generated_config is None:
            generated_config = StoredConfig(
                config_number, config_path, alias, str(captured["host"]),
                int(captured["port"]), captured_user,
            )
        print(f"已生成 OpenSSH 配置：{config_path}", file=sys.stderr)
        if args.auto_connect:
            client_name = args.client or ("scp" if args.scp else "ssh")
            result = connect_with_config(
                generated_config,
                client_name=client_name,
                client_arguments=client_arguments,
                askpass_helper=askpass_helper,
            )
            if result != 0:
                raise SSOParseError(f"{client_name} 退出，状态码 {result}")
            return 0

        if args.scp or args.client or client_arguments:
            raise SSOParseError(
                "创建隧道时不会主动启动客户端；"
                "请先单独运行链接，再在另一终端使用 -F/-S/-C"
            )
        print(
            f"UMA_BRIDGE_READY={generated_config.number}\n"
            f"隧道已在后台终端保持。新终端连接："
            f"{Path(sys.argv[0]).name} -F {generated_config.number}\n"
            f"按 Ctrl-C 停止隧道并清理配置。",
            file=sys.stderr,
            flush=True,
        )
        while process.poll() is None:
            time.sleep(0.5)
        raise SSOParseError(f"umasso 已退出，退出码 {process.returncode}")
    except KeyboardInterrupt:
        print("UMA 会话已停止。", file=sys.stderr)
        return 130
    except SSOParseError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    finally:
        if profile_backup is not None:
            try:
                restore_client_profile(profile, profile_backup)
            except SSOParseError as exc:
                print(f"严重警告：{exc}", file=sys.stderr)
        if process is not None:
            stop_process(process)
        stop_pid(capture_pid)
        if managed_config_path is not None:
            remove_stored_config(managed_config_path)
        if temporary_dir is not None:
            shutil.rmtree(temporary_dir, ignore_errors=True)


if __name__ == "__main__":
    def handle_termination(*_: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_termination)
    raise SystemExit(main())
