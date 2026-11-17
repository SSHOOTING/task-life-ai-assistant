# CI/CD 说明

本文说明当前仓库的 Pull Request 检查、发布包构建、蓝 PC 手工部署和 GitHub Actions 部署接口。

当前状态：

- 共享仓库已公开：`https://github.com/SSHOOTING/task-life-ai-assistant`
- CI workflow 和手工部署 workflow 已写入仓库；
- `main` 分支已推送；
- 蓝 PC 已通过本地发布脚本部署，`GoalOfOurs-MVP` 健康检查通过；
- GitHub Actions 尚未实际运行；
- GitHub Actions Secrets、分支保护和审批规则尚待配置。

## 1. PR 检查

工作流：`.github/workflows/ci.yml`

触发条件：

- Pull Request；
- push 到仓库。

执行内容：

1. Python 3.12；
2. `compileall`；
3. `LLM_MODE=mock` 下运行 `mvp/tests`；
4. 运行 `tests/acceptance`，预期 TC-001 通过，下一阶段 case 明确 skip；
5. 构建确定性发布 zip；
6. 重复构建并逐字节比较；
7. 上传 `goal-of-ours-mvp` artifact。

发布包包含 `mvp/` 和 `deploy/bluepc/`，排除数据库、日志、`.env`、密钥和缓存。

## 2. 蓝 PC 实际部署

当前实际部署结果：

| 项目 | 当前值 |
|---|---|
| 主机 | 由部署负责人本地配置，不写入仓库 |
| SSH 别名 | 由部署负责人本地配置，不写入仓库 |
| 应用根目录 | `C:\GoalOfOurs` |
| 当前版本目录 | `C:\GoalOfOurs\app\current` |
| 数据目录 | `C:\GoalOfOurs\data` |
| 日志目录 | `C:\GoalOfOurs\logs` |
| 计划任务 | `GoalOfOurs-MVP` |
| 本机端口 | `18765` |
| Tailnet 端口 | `18766` |
| Tailnet 地址 | 由管理员在私有运维记录中维护 |
| LLM 模式 | `mock` |

从开发机手工发布：

```powershell
cd <repository-root>
.\deploy\bluepc\deploy.ps1
```

健康检查：

```powershell
.\deploy\bluepc\healthcheck.ps1
```

回滚：

```powershell
.\deploy\bluepc\rollback.ps1
```

## 3. GitHub Actions 部署接口

工作流：`.github/workflows/deploy-bluepc.yml`

它只允许手工触发，并会：

1. 核验同一 `main` commit 的 CI 已成功；
2. 下载 CI artifact 并校验 SHA-256；
3. 用 SSH/SCP 上传发布包和远程部署脚本；
4. 在蓝 PC 调用 `deploy-release.ps1`；
5. 由部署脚本完成健康检查和失败回滚。

需要的 Repository Secrets：

| Secret | 用途 |
|---|---|
| `BLUEPC_HOST` | 从 GitHub Runner 可访问的蓝 PC 地址 |
| `BLUEPC_USER` | 部署账户 |
| `BLUEPC_SSH_KEY` | 临时部署私钥全文 |
| `BLUEPC_KNOWN_HOSTS` | 严格主机校验用的 known_hosts |

## 4. 当前网络限制

蓝 PC 当前通过 Tailscale 私有地址访问。GitHub Hosted Runner 不在这个 tailnet 内，所以除非采用以下任一方案，`deploy-bluepc.yml` 不能直接访问蓝 PC：

1. 在 GitHub Actions 中加入 Tailscale 认证并加入同一 tailnet；
2. 在蓝 PC 安装 GitHub Actions self-hosted runner，并让部署任务在本机执行；
3. 提供一个受限制的公网 SSH 入口。

当前建议：先使用已经验证的本地 `deploy.ps1` 由发布负责人手工部署；CI 只负责测试和构建 artifact。等团队规模上来后，再选择 Tailscale Action 或 Blue PC self-hosted runner。

## 5. 本地模拟

```powershell
$env:LLM_MODE = "mock"
python -m compileall -q mvp ci
python -m unittest discover -s mvp/tests -v
python -m unittest discover -s tests/acceptance -v
python ci/build_release.py --output dist/goal-of-ours-mvp.zip --release-id local
```

部署流程的本机隔离冒烟：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ci/smoke_deploy_bluepc.ps1
```

## 6. 尚未完成

- 首次 GitHub Actions CI 运行；
- GitHub Secrets 配置；
- `main` 分支保护和必需检查；
- GitHub Runner 到蓝 PC 的网络方案；
- 正式微信回调公网地址；
- 生产数据库迁移策略和备份周期；
- 发布审批人与回滚演练记录。

