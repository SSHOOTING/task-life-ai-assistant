# 蓝 PC 部署说明

本目录只负责把 `task-life-ai-assistant` 的 MVP 发布到单独管理的 Windows 主机
（下称“蓝 PC”）。蓝 PC 不保存 Git 仓库，也不是代码源；所有发布包都由开发机
从已提交的 Git 版本生成。

## 1. 当前部署契约

| 项目 | 值 |
| --- | --- |
| 访问地址（蓝 PC 本机） | `http://127.0.0.1:18765/` |
| 服务监听 | `0.0.0.0:18765` |
| 团队 Tailscale 地址 | `http://<蓝-PC-Tailscale-IPv4>:18766/` |
| 计划任务 | `GoalOfOurs-MVP`，当前用户登录时启动一次 |
| Python | `C:\Program Files\Python314\python.exe` |
| 代码目录 | `C:\GoalOfOurs\app\current` |
| 上一版本 | `C:\GoalOfOurs\app\previous` |
| 历史版本目录 | `C:\GoalOfOurs\app\releases` |
| 数据库 | `C:\GoalOfOurs\data\mvp.db` |
| 运行进程 PID | `C:\GoalOfOurs\data\mvp.pid` |
| 配置 | `C:\GoalOfOurs\config\mvp.env` |
| 日志 | `C:\GoalOfOurs\logs\mvp.stdout.log`、`mvp.stderr.log` |
| 发布包备份 | `C:\GoalOfOurs\backups\releases` |
| 数据库备份 | `C:\GoalOfOurs\backups\db` |

代码、数据库、日志和密钥配置相互分离。`mvp.env` 和数据库不会进入发布包或 Git。

## 2. 发布流程

在开发机 PowerShell 7 中运行：

```powershell
cd <repository-root>
.\deploy\bluepc\deploy.ps1
```

脚本会依次完成：

1. 检查被 Git 跟踪的文件没有未提交改动；
2. 用 `git archive` 从 `HEAD` 生成 zip，只包含 `mvp/`；
3. 校验包内没有 `__pycache__`、`.pyc`、数据库、日志或 `.env`；
4. 把发布包和运维脚本上传到 `C:\GoalOfOurs`；
5. 停止旧计划任务，确认 18765 端口不再被占用；
6. 备份上一版代码和数据库；
7. 解压到 staging，校验后切换到 `app\current`；
8. 注册并启动 `GoalOfOurs-MVP` 计划任务；
9. 等待 `/api/health` 返回 200；
10. 用 Tailscale Serve 把 tailnet 的 18766 转发到本机 18765（仅 tailnet，不启用公网 Funnel）。

如果 18765 被其他服务占用，脚本会停止并报告占用 PID，不会杀进程。需要换端口时先确认
蓝 PC 现状，再使用：

```powershell
.\deploy\bluepc\deploy.ps1 -Port 18766
```

Windows 计划任务停止时不一定连带终止 Python 子进程，因此启动脚本会把自己的 Python
PID 写入 `data\mvp.pid`。重复部署和回滚只会停止同时满足“Python 314 路径 +
`-m mvp.app` + 目标端口”的已验证进程；其他占用者仍会报错退出，不会被杀。

## 3. 健康检查与固定用例

从开发机执行：

```powershell
.\deploy\bluepc\healthcheck.ps1
```

该脚本会通过 SSH 在蓝 PC 检查计划任务、监听端口、`/api/health`、H5 首页，并提交一条
固定幂等用例：

```text
今天背完单词了，论文开头也改了，跟朋友聊完没那么焦虑了。
```

成功后应生成 2 条记录：一条“背单词”每日任务和一条“毕业论文”任务进展。脚本还会从
开发机通过蓝 PC 的 Tailscale IPv4 和 18766 端口直接请求 `/api/health` 与 H5 首页。

蓝 PC 当前有两条“Python 入站阻止”的 Windows 防火墙规则，因此 18765 不能从局域网或
Tailscale 直接访问。部署脚本不修改这些既有防火墙规则，而是用 Tailscale Serve 的 TCP
转发绕开应用进程入站限制。可用下面的命令查看当前 Tailscale IPv4：

```powershell
ssh <deployment-host-alias> "tailscale ip -4"
```

团队成员需在同一个 tailnet，然后打开 `http://<该 IPv4>:18766/`。18766 是 Tailscale
转发端口，不是第二个应用进程；18765 仍是唯一的 MVP 服务端口。

## 4. 密钥配置

首次部署创建 `C:\GoalOfOurs\config\mvp.env`，默认内容为 Mock 模式：

```dotenv
LLM_MODE=mock
SQLITE_PATH=C:\GoalOfOurs\data\mvp.db
```

`LLM_MODE=mock` 是强制开关：即使蓝 PC 的系统环境里已有 `OPENCODE_API_KEY`，MVP 也不会
调用真实模型。不要在聊天、脚本、日志或 Git 中粘贴真实密钥。

如后续明确需要连接真实模型，由密钥所有者直接在蓝 PC 上编辑该文件，填入
`OPENCODE_API_KEY` 并把 `LLM_MODE` 改为 `opencode`，然后通过计划任务重启服务。切换前需
确认测试原话是否允许发送给模型服务。

## 5. 日志

```text
C:\GoalOfOurs\logs\mvp.stdout.log
C:\GoalOfOurs\logs\mvp.stderr.log
C:\GoalOfOurs\logs\archive\
```

每次计划任务启动时，旧的当前日志会移到 `archive`，新日志从空文件开始。日志中不应出现
API Key；如发现密钥或 Cookie，应立即停止共享并清理对应日志。

## 6. 回滚

默认只回滚代码，保留当前数据库，避免丢失集成测试数据：

```powershell
.\deploy\bluepc\rollback.ps1
```

需要同时恢复最近一次部署前数据库备份时：

```powershell
.\deploy\bluepc\rollback.ps1 -RestoreLatestDatabase
```

数据库恢复会覆盖 `C:\GoalOfOurs\data\mvp.db`。脚本会先把当前数据库另存到
`C:\GoalOfOurs\backups\db\mvp-before-rollback-*.db`，但最近一次部署之后新增的数据仍不会
出现在恢复后的数据库中。

回滚是单步的：当前版本会移到 `app\releases\rolled-back-*`，`app\previous` 切换为
`app\current`。如需再次回滚，需要先从历史版本人工建立新的 `app\previous`。

## 7. 安全检查

- 所有远程写入路径会解析为绝对路径，并限制在 `C:\GoalOfOurs` 内；
- 脚本不会删除 `C:\LifeBot`、其他计划任务或未知端口进程；
- 脚本不申请管理员权限；
- 计划任务只在当前用户登录时启动一次，没有每分钟轮询或常驻监控；
- Tailscale 只提供 tailnet 内 TCP 转发，不启用公网 Funnel；
- 发布包由 Git 提交构建，不直接复制开发机的运行目录。
