# Windows 便携版：解压后启动

适用于 **Windows x64**。当前是未签名的 v0.1 开发预览，不是 `.msi` 安装器，也不是 Windows ARM64 包。Windows 11 已作为本机验收环境；Windows 10 和真实多网卡、Wi-Fi 漫游、USB 外设仍需单独实机验收。

## 第一次打开

1. 将 ZIP **完整解压**到自己的文件夹，例如 `D:\Tools\MacNetLab`。不要在压缩包内运行，也不要单独移动 `.exe`；旁边的 `_internal` 必须保留。
2. 双击 `MacNetLab.exe`（或 `Start-MacNetLab.cmd`）。无需安装 Python、Node.js，无需管理员权限。
3. 等待启动窗口显示地址，浏览器会打开 [本地工作台](http://127.0.0.1:8765)。没有自动打开时手动访问该地址。
4. 示例不会自动探测网络。先描述拓扑，为获授权目标配置检测，再「运行一次」。

**窗口保留不是卡住**：它是本机服务。关闭网页不会停止采集。在「连接设置 → 常规 → 退出工作台」确认退出，或回到启动窗口按 `Ctrl+C`，可正常停止。

重复打开同一数据目录的程序会打开已有工作台，不启动第二个采集器。如果端口被其他程序或不同数据目录的工作台占用，会拒绝启动；不会停止该程序，也不会打开它的页面。升级前先退出旧版本，否则旧版本缺少实例身份时也会提示占用。

## 数据、更新和卸载

- 默认数据在 `%LOCALAPPDATA%\MacNetLab`，与解压目录分开。沿用旧 Windows 预览创建的数据库时，可能继续使用 `~/Library/Application Support/MacNetLab`，以启动窗口实际显示为准。
- 若希望数据也放在 D 盘，用终端启动：

  ```powershell
  .\MacNetLab.exe --data-dir "D:\MacNetLabData"
  ```

  日后始终使用相同参数；也可为这条命令建立自己的快捷方式。直接双击会回到默认数据目录。
- 更新：退出旧版本，备份完整数据目录，解压新版到另一个文件夹，使用相同数据目录启动；原目录保留作回退。不要把新版覆盖到正在运行的目录。
- 卸载：退出后删除解压文件夹即可。诊断数据库和系统凭据不自动删除；需要时由用户分别清理。软件不注册开机启动、不修改网络和防火墙。
- 凭据仍使用 Windows Credential Manager，报告仍在本机生成；软件不接入 AI。分享前检查报告中的地址、主机名、SSID 和备注。

## 下载与提示

GitHub 仓库的 **Actions → Checks → 成功运行 → Artifacts → macnet-lab-windows-x64** 提供自动构建产物（下载 Actions 产物需要 GitHub 登录）。解开 Artifact 的外层 ZIP，再解开其中的应用 ZIP。源码页的「Download ZIP」是源码，不是便携程序。

开发预览没有代码签名，Windows 或安全软件可能提示未知发布者。只使用可信仓库的成功构建；若被拦截，保留错误信息并反馈，不关闭系统防护。没有自动更新或静默安装。

## 开发者构建

在 Windows x64 和 Python 3.11+ 环境、项目根目录执行（构建前端还需 Node.js 22.12+）：

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
python -m pip install ".[windows-build]"
python scripts/build-windows.py
# 需空闲的本机 8765 端口；只测试独立临时数据库和本机资源：
python scripts/smoke-windows.py dist/windows/MacNetLab/MacNetLab.exe
```

发行包也可执行 `MacNetLab.exe --check-runtime`：检查 TLS 证书校验、Windows 凭据后端加载与内置界面，不读取或写入任何凭据，不启动采集。构建验收还会在移除 Python / Node 的 PATH 下运行独立临时数据库，测试导出、重复启动、退出和重开。

可通过 `--output`、`--work` 指定 D 盘构建输出与中间目录。采用 PyInstaller onedir，不在每次运行时解包整套 Python 到系统临时目录；原理与参数见 [PyInstaller 官方文档](https://pyinstaller.org/en/stable/spec-files.html)。运行程序不需要构建工具；保留所有依赖的许可证。

## English quick start

Unzip the entire folder on Windows x64 and double-click **MacNetLab.exe**. Keep `_internal` beside it. Python and Node.js are bundled/not required for daily use. Keep the console open; stop via **连接设置 → 常规 → 退出工作台**, or press **Ctrl+C** in that console. Closing the browser does not stop collection.

Data defaults to `%LOCALAPPDATA%\MacNetLab` (legacy preview data can retain its original location). Use `MacNetLab.exe --data-dir "D:\MacNetLabData"` for another location and keep that argument on subsequent launches. Quit and back up data before upgrading. A duplicate launch reuses only the same live data directory; occupied ports and mismatched directories fail without terminating anything. This unsigned development preview does not register startup tasks or change firewall/network settings. No in-app AI connection is needed: export Markdown/JSON and share manually.
