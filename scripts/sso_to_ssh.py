#!/usr/bin/env python3
"""Parse a Huawei UMA sso:// URL and emit a safe OpenSSH configuration."""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import ipaddress
import json
import re
import shlex
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote


MAX_URL_LENGTH = 64 * 1024
SAFE_USER = re.compile(r"^[A-Za-z0-9_.@\\-]+$")
SAFE_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")


class SSOParseError(ValueError):
    pass


@dataclass(frozen=True)
class SSOConnection:
    mode: str
    gateway_host: str
    gateway_port: int
    tunnel_port: int | None
    tunnel_fingerprint: str
    asset_host: str
    asset_port: int
    asset_user: str
    asset_name: str
    asset_protocol: str
    uma_user: str
    has_sso_token: bool
    has_tunnel_token: bool


def _value(data: dict[str, Any], *names: str, default: Any = "") -> Any:
    folded = {str(key).casefold(): value for key, value in data.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return default


def _port(value: Any, field: str, *, optional: bool = False) -> int | None:
    if value in (None, "") and optional:
        return None
    try:
        port = int(str(value), 10)
    except (TypeError, ValueError) as exc:
        raise SSOParseError(f"{field} 不是有效端口") from exc
    if not 1 <= port <= 65535:
        raise SSOParseError(f"{field} 超出 1-65535 范围")
    return port


def _host(value: Any, field: str) -> str:
    host = str(value or "").strip()
    if not host:
        raise SSOParseError(f"缺少 {field}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not SAFE_HOSTNAME.fullmatch(host):
            raise SSOParseError(f"{field} 包含不安全或无效字符")
    return host


def _user(value: Any, field: str) -> str:
    user = str(value or "").strip()
    if not user:
        raise SSOParseError(f"缺少 {field}")
    if not SAFE_USER.fullmatch(user):
        raise SSOParseError(f"{field} 包含 OpenSSH 配置不支持的字符")
    return user


def _decode_payload(link: str) -> dict[str, Any]:
    link = link.strip()
    if not link:
        raise SSOParseError("没有收到 SSO 链接")
    if len(link) > MAX_URL_LENGTH:
        raise SSOParseError("SSO 链接过长")
    scheme = next(
        (candidate for candidate in ("sso://", "umasso://") if link.casefold().startswith(candidate)),
        None,
    )
    if scheme is None:
        raise SSOParseError("链接必须以 sso:// 或 umasso:// 开头")

    payload = unquote(link[len(scheme) :]).strip()
    if not payload or any(char in payload for char in "?#"):
        raise SSOParseError("SSO 链接负载为空或格式无效")
    payload = "".join(payload.split())
    payload += "=" * (-len(payload) % 4)
    try:
        raw = base64.b64decode(payload, altchars=b"-_", validate=True)
        decoded = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SSOParseError("SSO 链接不是有效的 Base64 JSON") from exc
    if not isinstance(decoded, dict):
        raise SSOParseError("SSO JSON 顶层必须是对象")
    return decoded


def parse_sso(link: str) -> SSOConnection:
    decoded = _decode_payload(link)
    node = _value(decoded, "NODE_COMMON", "NodeCommon", default=decoded)
    if not isinstance(node, dict):
        raise SSOParseError("NODE_COMMON 必须是对象")

    protocol = str(_value(node, "AssetProtocol", "Protocol", default="SSH")).upper()
    if protocol != "SSH":
        raise SSOParseError(f"资产协议是 {protocol!r}，不是 SSH")

    asset_name = str(_value(node, "AssetName", default="")).strip()
    return SSOConnection(
        mode=str(_value(node, "Mode", default="")),
        gateway_host=_host(_value(node, "IPv4", "Host"), "IPv4/网关地址"),
        gateway_port=_port(_value(node, "Port"), "Port"),  # type: ignore[arg-type]
        tunnel_port=_port(_value(node, "TunnelPort"), "TunnelPort", optional=True),
        tunnel_fingerprint=str(_value(node, "TunnelFingerprint", default="")).strip(),
        asset_host=_host(_value(node, "AssetIPv4", "AssetHost"), "AssetIPv4/资产地址"),
        asset_port=_port(_value(node, "AssetPort", default=22), "AssetPort"),  # type: ignore[arg-type]
        asset_user=_user(_value(node, "AssetUser"), "AssetUser"),
        asset_name=asset_name,
        asset_protocol=protocol,
        uma_user=str(_value(node, "Username", default="")).strip(),
        has_sso_token=bool(_value(node, "SSOToken", "SsoToken", default="")),
        has_tunnel_token=bool(_value(node, "TunnelToken", default="")),
    )


def safe_alias(connection: SSOConnection, requested: str | None) -> str:
    source = requested or connection.asset_name or connection.asset_host
    alias = re.sub(r"[^A-Za-z0-9_.-]+", "-", source).strip("-.")
    if not alias:
        alias = "asset"
    if alias[0] == "-":
        alias = f"asset{alias}"
    return f"uma-{alias}"[:128]


def render_config(
    connection: SSOConnection,
    route: str,
    alias: str,
    local_host: str,
    local_port: int | None,
) -> str:
    if route == "local":
        if local_port is None:
            raise SSOParseError("local 模式必须提供 --local-port")
        host = _host(local_host, "local-host")
        port = _port(local_port, "local-port")
        route_note = "经已启动的 UMA 本地隧道连接"
    else:
        host = connection.asset_host
        port = connection.asset_port
        route_note = "直接连接资产；仅在本机网络能够访问该资产时有效"

    lines = [
        "# Generated by sso_to_ssh.py; tokens are intentionally omitted.",
        f"# Route: {route_note}",
        f"# UMA gateway: {connection.gateway_host}:{connection.gateway_port}",
    ]
    if connection.tunnel_port:
        lines.append(
            f"# UMA server-side tunnel endpoint: "
            f"{connection.gateway_host}:{connection.tunnel_port} (not a local SSH port)"
        )
    lines.extend(
        [
            f"Host {alias}",
            f"    HostName {host}",
            f"    Port {port}",
            f"    User {connection.asset_user}",
            f"    HostKeyAlias {connection.asset_host}",
            "    ServerAliveInterval 30",
            "    ServerAliveCountMax 3",
        ]
    )
    return "\n".join(lines) + "\n"


def render_summary(connection: SSOConnection) -> str:
    fingerprint = connection.tunnel_fingerprint or "(未提供)"
    return "\n".join(
        [
            f"资产名称: {connection.asset_name or '(未提供)'}",
            f"资产 SSH: {connection.asset_user}@{connection.asset_host}:{connection.asset_port}",
            f"UMA 用户: {connection.uma_user or '(未提供)'}",
            f"UMA 网关: {connection.gateway_host}:{connection.gateway_port}",
            f"UMA 隧道: {connection.gateway_host}:{connection.tunnel_port or '(未提供)'}",
            f"隧道指纹: {fingerprint}",
            f"SSO Token: {'存在（不输出）' if connection.has_sso_token else '缺失'}",
            f"Tunnel Token: {'存在（不输出）' if connection.has_tunnel_token else '缺失'}",
        ]
    ) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="解析华为 UMA sso:// 链接并生成不含 Token 的 OpenSSH 配置。"
    )
    parser.add_argument(
        "--route", choices=("direct", "local"), default="direct",
        help="direct 直连资产；local 连接 UMA 已建立的本地转发（默认 direct）",
    )
    parser.add_argument("--local-port", type=int, help="local 模式下 UMA 暴露的本地端口")
    parser.add_argument("--local-host", default="127.0.0.1", help="本地转发监听地址")
    parser.add_argument("--alias", help="生成的 OpenSSH Host 别名")
    parser.add_argument(
        "--format", choices=("config", "command", "summary"), default="config",
        help="输出 SSH 配置、命令或脱敏摘要",
    )
    return parser


def read_link(prompt: str = "请粘贴 sso:// 或 umasso:// 链接（输入不会回显）: ") -> str:
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return sys.stdin.read()


def main() -> int:
    args = build_parser().parse_args()
    try:
        connection = parse_sso(read_link())
        alias = safe_alias(connection, args.alias)
        if args.format == "summary":
            sys.stdout.write(render_summary(connection))
        elif args.format == "command":
            if args.route == "local":
                if args.local_port is None:
                    raise SSOParseError("local 模式必须提供 --local-port")
                host, port = _host(args.local_host, "local-host"), _port(args.local_port, "local-port")
            else:
                host, port = connection.asset_host, connection.asset_port
            command = ["ssh", "-p", str(port), f"{connection.asset_user}@{host}"]
            sys.stdout.write(" ".join(shlex.quote(part) for part in command) + "\n")
        else:
            sys.stdout.write(
                render_config(connection, args.route, alias, args.local_host, args.local_port)
            )
        if args.route == "direct" and connection.has_tunnel_token:
            print(
                "提示：链接包含 UMA 隧道信息；direct 配置仅在资产地址可直达时有效。"
                "若 UMA 客户端提供本地端口，请使用 --route local --local-port PORT。",
                file=sys.stderr,
            )
        return 0
    except SSOParseError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
