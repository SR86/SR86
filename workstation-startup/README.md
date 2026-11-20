# Windows 远程工作站网络自动化

## 文件

- `network_watchdog.py`：持续检测网络、有限次数重新认证和打开断网助手。
- `campus_login.py`：Edge / Playwright 校园网认证，成功需通过直连 HTTPS 检测。
- `network_check.py`：绕过代理、验证证书、拒绝重定向的联网检测。
- `save_credentials.py`：在本机交互输入账号密码，通过 keyring 保存到 Windows 凭据存储。
- `remaining-startup.ps1`：等联网后启动已有 Clash Verge，检查代理内核、Tailscale、RustDesk 服务与连接状态。
- `test_reconnect.py`：模拟网络故障测试，不主动断开真实网络。

## 当前行为

正常联网时每小时检测一次，发现异常后每20秒确认，连续两次失败才尝试认证。认证服务器可达时，每轮最多尝试3次，重试间隔约30秒、120秒，随后冷却15分钟。凭据缺失、明确拒绝或页面结构变化会停止认证提交。

认证失败且外网复查失败时，打开已安装的360断网急救箱，同一小时最多启动一次，限频状态跨进程重启保留。**只实现自动打开，鼠标录制、自动点击诊断和修复尚未完成。** 休眠、物理断线或上游故障无法通过认证脚本解决。

## 本机配置

1. 创建 Python 虚拟环境，安装 `requirements.txt`，并安装 Microsoft Edge。
2. 核对 `campus_login.py` 的学校入口和表单选择器、`network_check.py` 的服务器地址。当前示例来自一个特定校园网，不能直接用于所有学校。
3. 在本机运行 `python save_credentials.py`。不把真实凭据写入脚本或提交仓库。当前校园网入口使用 HTTP，keyring 仅保护本地存储，不能加密认证网络传输。
4. 执行 `python network_watchdog.py --check` 检查网络，执行 `python -m unittest test_reconnect` 运行模拟测试。
5. 通过任务计划程序在当前用户登录后启动虚拟环境的 `pythonw.exe`，参数为 `network_watchdog.py` 的完整路径，起始目录为本目录。使用交互式会话、短延迟、忽略重复实例、无执行时限；请更新已有 CampusAutoLogin，避免重复创建。此仓库不自动创建任务或保存 Windows 登录密码。
6. `remaining-startup.ps1` 中的 Clash 路径、Tailscale 路径和服务名需按本机核对。可通过已有登录任务运行；该脚本只检查服务，不安装或配置无人值守服务、不更改节点、TUN、防火墙或 ACL。

日志保存在 `logs/`，状态保存在 `network-watchdog-status.json`，这些文件不上传。急救箱路径需在 `network_watchdog.py` 中核对。运行依赖 Windows 用户登录，锁屏和注销下的 GUI 操作未验证。

## 停止与恢复

停止已有 CampusAutoLogin 即暂停监控，启动任务恢复。修改前请在本机备份脚本并导出任务 XML；回退时停止任务、还原本机备份和任务设置，再启动。仓库不包含个人任务 XML、数据库、日志、凭据或旧备份。
