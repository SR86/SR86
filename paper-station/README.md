# 论文小站源代码

Windows 本地运行的论文阅读、任务管理和 Codex 自动执行工作站。

- quota-web：网页、任务队列、上传、结果导出、存档及执行器。
- quota-notifier：额度监控、通知去重和 Windows 应用包启动支持。
- gotify：本地 Gotify 启动及通知应用连接脚本（不包含服务器二进制）。

## 部署

安装 Python 及 requirements.txt 中依赖。复制 quota-notifier/runtime.example.json 为 runtime.json，将 codex_path 改为本机实际 CLI 路径。按需修改 quota-web/control.py 的 PAPERS 和源码中占位域名 your-device.your-tailnet.ts.net。

在 Windows 凭据管理器中通过 keyring 设置 Gotify 凭据：服务 CodexQuotaNotifier.Gotify，admin 为管理员密码，app_token 为应用令牌。切勿提交凭据文件。

网页入口为 quota-web/console_server.py，仅监听本机 8768；手机访问需自行配置 Tailscale Serve。Codex 执行依赖本机登录、相应 Windows 沙箱和真实应用包环境；单独启动网页不代表执行器已可用。quota-notifier/package_launch.py 支持应用包启动。

本仓库不包含论文、数据库、日志、任务结果、虚拟环境、个人运行配置和密码。源码中的电脑域名、用户路径已替换为示例；运行中的本地项目未改动。历史兼容页面保留，当前页面使用 ui.html、app-v2.js、management-v2.js、style-v2.css。

日间新增额度软预算为30个百分点，凌晨策略见 executor.py。部署前请根据自己的使用安排核对。
