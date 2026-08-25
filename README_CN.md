# UMA SSO Skill

通过持久化 Huawei UMA 隧道，让 AI Agent 复用 SSH 配置进行 SSH、SCP 和 SFTP 访问。

---

[English](README.md)

---

## 功能特性 ✨

- 将后台 UMA bridge 与前台 SSH 会话分开管理
- 多次 SSH、SCP 和 SFTP 操作复用同一个隧道
- 自动生成并校验托管的 OpenSSH 配置
- 支持通过 Agent 安装为 skill，也可添加 `uma` shell 函数

## 兼容性 🖥️

- Linux 或 WSL
- Bash 和 Python 3
- 当前版本：x86_64/amd64
- 有效的 Huawei UMA `sso://` 或 `umasso://` 访问链接

由于版权原因，请将 `assets/umasso` 替换为你从 Huawei UMA 官方渠道下载且有权使用的可执行程序。当前文件为 amd64 版本；如需 aarch64 或其他架构，请替换为对应的官方程序，并相应调整 `scripts/run.sh` 中的架构检查。

## 安装 🚀

### 使用 Skills CLI

```bash
npx skills add cornjosh/uma-sso-skill
```

### 让 Agent 安装

你也可以直接在 Codex、Claude Code、OpenCode 或其他支持 skill 的 Agent 中发送：

```text
请阅读并将 https://github.com/cornjosh/uma-sso-skill 安装为当前环境可用的 Agent Skill。
```

如果仓库为私有状态，请确保 Agent 所在环境已经登录有访问权限的 GitHub 账号。

### 在终端直接使用

如果希望在 shell 中直接运行 `uma`，可以让 Agent 阅读仓库中的 shell 安装说明：

```text
请阅读 https://github.com/cornjosh/uma-sso-skill，并按照 references/install-shell.md 为当前 shell 安装 uma 命令。
```

## 获取 SSO 链接 🔑

1. 登录 Huawei UMA 页面。
2. 在“运维 → 资产 → 访问”中找到需要通过 SSH 访问的资产。
3. 按 `F12` 打开浏览器开发者工具，切换到“网络（Network）”选项卡。
4. 选择合适的账号、`SSH`、密码认证、“不使用远程客户端”和“本地运维”方式，然后点击登录。
5. 在网络请求中复制以 `sso://` 开头的访问 URL。

## 用法 ⌨️

在后台终端启动 UMA bridge，等待输出 `UMA_BRIDGE_READY=N`：

```bash
scripts/run.sh 'sso://...'
```

在其他终端中复用同一个 `N`：

```bash
# SSH
scripts/run.sh -F N

# SCP
scripts/run.sh -S -F N ./local-file :/remote/path

# SFTP
scripts/run.sh -C sftp -F N
```

开始连接前，请先阅读 [SKILL.md](SKILL.md) 中的完整操作和安全说明。

## 工作方式 🔧

```text
后台终端：UMA bridge
    └── 维护隧道并生成 SSH config

前台终端：SSH / SCP / SFTP
    └── 复用同一个 config，可随时退出和重连
```

## 项目结构 📦

```text
SKILL.md                    Agent 操作说明
scripts/run.sh              统一入口
scripts/uma_sso_bridge.py   UMA bridge 管理器
references/install-shell.md shell 函数安装说明
assets/umasso               需要替换的 Huawei UMA 官方程序
```
