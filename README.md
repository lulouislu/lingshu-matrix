# MacNet Lab

**让 AI 看懂你的网络，再沿着证据找到问题。**

面向 macOS 的本地网络运维工作台：用拓扑描述设备、接口与服务，把当前接入位置、检测记录和故障现场一起交给 AI 分析。

MacBook 接一根机房网线、连任意一个 AP，或常开 Mac 同时使用有线与 Wi-Fi，都可以是观测入口。**双网不是使用前提。**

> **v0.1 开发预览**：已有可运行程序、自动化测试和安装脚本。通用功能已在 Windows 开发环境验证；macOS 网卡绑定、CoreWLAN、打印、钥匙串及登录常驻仍需真实 Mac 验收。当前没有签名的 `.app` / `.dmg` 安装包。

![MacNet Lab 开发环境中的家庭示例拓扑](docs/workbench.png)

_界面为开发预览；示例拓扑没有配置真实地址或启用自动检测。_

## 先把一项检测跑起来

### 在 Mac 上从源码安装

准备 Python 3.11+、Node.js 22.12+（建议 24）和 Git，然后在终端执行：

```bash
git clone https://github.com/lulouislu/macnet-lab.git
cd macnet-lab
bash scripts/install-macos.sh
bash scripts/start-macos.command
```

安装使用项目内 `.venv`，不需要 `sudo`。首次构建需要下载 npm / PyPI 依赖；之后日常运行不需要 Node.js。

打开 [本地工作台](http://127.0.0.1:8765)。首次启动的示例**不会探测你的网络**。

1. 选择示例或创建空白站点，点击「编辑拓扑」，添加设备并从接口圆点拉线。
2. 点击设备填写管理地址、服务、接口信息；当前 Mac 勾选「这是运行工作台的本机 Mac」。
3. 添加一项检测，先点「运行一次」，在「结果详情」查看指标与实际配置的检测路径。
4. 要持续采集时，再勾选检测的「自动检测」、保存，并点击「开始监控」。
5. 连续失败达到阈值后，在「故障黑匣子」查看现场证据，或交给「AI 排障」。

停止前台程序：在启动终端按 `Ctrl+C`。关闭浏览器不等于停止采集。

### 可选：登录后常驻

先停止手动启动的实例，再执行：

```bash
.venv/bin/python scripts/login-item.py install
.venv/bin/python scripts/login-item.py status
# 停止常驻并取消登录启动，保留数据库和钥匙串：
.venv/bin/python scripts/login-item.py remove
```

这是当前用户的 LaunchAgent，不是 root 服务。只有用户登录且 Mac 醒着时才能采集；迁移项目目录后需要重新安装登录项。此入口已实现，等待真实 macOS 验收。

## 用拓扑说明环境，不让 AI 猜接线

内置两类示例，也支持空白站点：

```text
单 AC / 多 AP：
网关 ── 交换机 ── AC、AP 1、AP 2
AC  ··· 管理关系 ··· AP 1 / AP 2
AP 1 ── Wi-Fi ── 维护 MacBook

家庭实验室（两处 Mac 是同一台）：
光猫 ── 路由器 1 ── Wi-Fi ── Mac
     └─ KWRT / Nikki ── 有线 ── Mac ── USB ── 打印机
                                  └─ 运行：打印共享、Minecraft
```

- **有线、Wi-Fi、USB** 连到具体接口；**管理关系、服务依赖** 单独表达。
- AP 可以配置多个 BSSID。读取到当前 BSSID 后，只有唯一匹配才关联 AP；不凭 SSID 猜设备。
- 服务名称、设备备注用于补充 VLAN、DHCP / DNS 角色、部署位置等上下文；这些角色目前还不是独立的结构化配置项。
- 声明的拓扑与实际观测分开。看不到管理网，不会自动改 VLAN、路由或访问控制。

## 当前可以做什么

| 能力         | 当前实现与边界                                                                                        |
| ------------ | ----------------------------------------------------------------------------------------------------- |
| 拓扑编辑     | 拖拽设备、接口连线、多站点、乐观锁保存、JSON 导入导出、PNG 与浏览器打印                               |
| 当前接入     | 接口、IPv4 / IPv6 地址、可用速率与计数器；macOS 适配接口作用域网关、DNS、Wi-Fi SSID / BSSID / RSSI 等 |
| 网络检测     | ICMP、TCP、DNS、HTTP(S)、显式 HTTP / SOCKS 代理、Mihomo 控制 API                                      |
| 路径隔离     | macOS IPv4 socket 绑定接口；HTTP 绑定 socket 并显式解析；绑定失败不回退。默认路径会明确标为 `system`  |
| 故障黑匣子   | 连续失败阈值、重复事件合并、异常快照、连续两次成功确认恢复、手动补采、证据导出                        |
| 中断识别     | 接口 / 地址 / 网关 / BSSID 变化、程序重启及超过 60 秒的调度缺口会中断旧事件，不伪装成恢复             |
| Mac 打印     | 读取 CUPS、队列数量与 USB 枚举；不发测试打印任务，不自动把普通打印共享变成 AirPrint                   |
| Minecraft    | Java / Bedrock 只读状态协议，版本、人数、请求耗时；本机资源可附加指定 PID 的内存与累计 CPU 时间       |
| KWRT / Nikki | 已校验主机公钥的 SSH 固定只读命令组；Mihomo API 状态与显式代理上网分别检测                            |
| AI 分析      | 本地规则摘要、Codex App Server 实验适配、OpenAI 兼容 API；外发预览与明确同意，无静默切换              |

### 怎样分别检测有线与 Wi-Fi

为同一目标创建两项检测，各自选择真实的采集源接口。绑定接口访问域名时，填写该路径的 **IPv4 DNS 服务器**，防止借另一接口解析。

现场维护中不常用的第二接口，取消「此接口必须在线」：它断开时记为暂停，而不是故障。接口名称从系统读取，不写死 `en0` / `en1`。

当前主动检测以 **IPv4** 为主；IPv6 主动探测未实现。SSH 只读采集使用系统管理路径，配置接口绑定时会显示未知而不执行。VPN / 透明代理的端到端实际出口、其他 AP 的覆盖和其他玩家的公网可达性，需要对应位置的额外证据。

### 打印和 Minecraft 的判断范围

USB 打印机无需填写 IP。CUPS 可查询、USB 已枚举、手机可发现、实际打印成功是不同事实；本工具目前覆盖前两类本机只读信息。

Minecraft 协议响应与进程资源分开采集。服务进程 PID 需要手动维护；PID 重用、重启后请核对进程名和创建时间。当前不读世界存档、聊天或完整服务器日志，也不报告未采集的 TPS / MSPT。

## 连接 AI

默认使用**本地规则摘要**，不调用模型、不外发资料。

### Codex（实验适配）

先安装[官方 Codex CLI](https://developers.openai.com/codex/cli)，通过本工具入口完成一次独立登录：

```bash
.venv/bin/macnet-lab --codex-login
```

登录由官方 CLI 处理。MacNet 使用数据目录里的独立 `codex-home`，不复制桌面端凭据、插件或 MCP 配置。适配器使用临时工作目录、受限只读沙箱，关闭 Shell、Apps、Hooks、多代理与搜索；模型调用前检查 MCP 清单，发现外部服务器即停止。协议测试已通过，真实账号模型问答尚未验收。

### OpenAI 兼容 API

在「连接设置」填写 API 基础地址、模型名称及密钥。支持 HTTPS 提供商，也允许本机 HTTP 模型服务。密钥进入系统钥匙串；系统钥匙串不可用时直接报错。本机无认证模型服务可以留空；更换 API 基础地址时不会沿用其他地址的密钥。

在「AI 排障」选择提供商，先「预览将发送的证据」，再确认发送。云模型可能消耗你的账号额度或 API 费用。服务失败会显示错误，不会自动切换 DeepSeek 或其他提供商。

**外发数据仍可能包含 IP、SSID、BSSID、设备名称和备注。** 凭据字段、私钥、常见令牌、订阅 URL、UUID 与序列号做规则脱敏，不能代替人工检查；不要在自由文本中填写密码。

## 数据、安全与恢复

- 只监听 `127.0.0.1:8765`，校验 Host / Origin，并使用本机会话 Cookie 和写请求确认头；不提供局域网或公网管理模式。
- 默认数据目录：`~/Library/Application Support/MacNetLab`。可用 `--data-dir /path/to/data` 指定。配置、历史和快照在 SQLite，设备凭据在系统钥匙串，已核实公钥在独立 `known_hosts`。
- SSH 不自动信任新主机，不使用 SSH agent 或任意 Shell 输入。先经可信渠道核实公钥，再在设置粘贴完整 OpenSSH 记录。保存会替换本工具原有记录。
- 默认保留 7 天，可设置 1–30 天；另有样本 / 证据行数上限、单条输出上限与数据盘低空间暂停。SQLite 主库设置约 512 MiB 页面上限；WAL 与独立 Codex 目录不计入这个上限。
- JSON 导出移除凭据引用并禁用检测，导入创建新站点。**IP、BSSID 和备注保留**；截图和证据导出也需要人工检查后再分享。
- 完整备份：停止采集程序，备份整个数据目录；钥匙串单独保留。拓扑 JSON 只用于交换配置，不是历史记录备份。

首版只读，不修改 LAN、DHCP、防火墙、系统路由、打印配置、Minecraft 存档或玩家权限。**受控修复、设备端 watchdog 和回滚审计仍未实现**，不会把 `sleep 45` 当作可靠恢复承诺。

## 开发与验证

Vue 3 + TypeScript + Vue Flow；FastAPI + asyncio；SQLite；AsyncSSH；CoreWLAN / psutil / keyring。

macOS / Linux 开发测试：

```bash
python3 -m venv .venv
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
.venv/bin/python -m pip install '.[dev]'
.venv/bin/python -m pytest -q
```

Windows 仅用于通用开发预览，后两步使用 `.venv\Scripts\python.exe`；启动时明确加 `--preview`：

```powershell
.venv\Scripts\python.exe -m macnet.cli --preview --data-dir .\data
```

生产前端输出到 `macnet/static`，不提交生成文件。发布 Python 包前必须先构建前端。`python -m build` 打包的 wheel 包含已构建界面，源码仓库直接 `pip install .` 而未构建前端时会提示 503。

提交会触发 macOS / Linux / Windows CI；CI 结果看 [Actions](https://github.com/lulouislu/macnet-lab/actions)，不把配置了 CI 当作已通过真实设备验收。

## 接下来完成什么

- [x] 拓扑 → 只读检测 → 故障快照 → 本地证据分析闭环。
- [x] 打印、USB、Minecraft、KWRT / Nikki 的限定采集适配与安装入口。
- [x] AI 外发预览、提供商选择、凭据隔离和协议测试。
- [ ] [真实 Mac 验收](docs/MAC_ACCEPTANCE.md)：单有线、单 Wi-Fi、单 AC 多 AP、双接口不串路、休眠恢复、打印与钥匙串。
- [ ] 真实 Codex / 自定义模型问答验收；不使用真实网络日志做自动付费测试。
- [ ] 图表化历史、IPv6 主动探测、设备控制器深度指标、受限 Minecraft 日志。
- [ ] 参数化受控修复：逐动作确认、设备端恢复、验证与审计，通过故障注入演练后再启用。
- [ ] 签名 / 公证的 macOS 应用包与 Intel / Apple Silicon 兼容性确认。

欢迎用脱敏拓扑与复现步骤提交 Issue。代码采用 [MIT License](LICENSE)；依赖保留各自许可证。
