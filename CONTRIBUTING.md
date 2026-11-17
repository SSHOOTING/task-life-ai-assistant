# Git 协作规范

本文档约定 `task-life-ai-assistant` 共享仓库的分支、提交、评审、测试和数据安全规则。所有成员在开始开发前都应先阅读本文档。

## 1. 分支模型

- `main` 是唯一集成分支和保护分支，始终应保持可运行、可测试。
- 禁止直接向 `main` 提交或推送开发改动。
- 所有开发从最新的 `main` 创建功能分支：

```text
feature/<area>-<topic>
```

- 建议使用以下区域标识：
  - `feature/a-channel`：渠道、公众号、H5 和用户入口；
  - `feature/b-orchestrator`：编排、教练、回执和跨模块流程；
  - `feature/c-data-parser`：解析、数据访问、记录和存储。
- 示例：`feature/c-data-parser-correction-idempotency`。
- 主题使用小写英文和连字符，描述一个可以独立评审的问题。

## 2. 一个 PR 只解决一个问题

- 每个 Pull Request 只处理一个明确问题，避免把重构、格式化、功能开发和数据变更混在一起。
- PR 描述至少包含：问题、改动范围、验证方式、风险、回滚方式和相关截图或日志。
- 涉及界面或渠道状态时，截图必须先检查并移除二维码、手机号、Cookie、Token、登录态、AppSecret 和真实用户隐私。

## 3. 合入规则

- 合入前必须通过相关单元测试、契约测试和迁移检查。
- 当前基础测试命令：

```powershell
$env:LLM_MODE = "mock"
python -m compileall -q mvp ci
python -m unittest discover -s mvp/tests -v
python -m unittest discover -s tests/acceptance -v
```

- 改动共享接口、共享字段或状态枚举时，必须同时补充或更新契约测试。
- 改动数据库 schema、初始化脚本或迁移文件时，必须执行迁移检查，并验证新数据库创建和旧数据库升级路径。
- 至少一名其他成员完成评审并批准后才能合入。
- 合入统一使用 **squash merge**（压缩合并）：一个功能 PR 在 `main` 上形成一个清晰的提交。仓库初始化阶段已有的 merge commit 保留，不回写历史。
- 合并后删除远程功能分支。

## 4. contracts 与跨区域变更

- 共享字段、接口、请求/响应结构、错误码和状态枚举只能先修改 `contracts/` 中的约定，再修改实现。
- `contracts/` 是跨区域约定的唯一来源，当前已建立 `contracts/openapi.yaml` 和契约说明；新增或修改契约仍须评审。
- 修改 `contracts/` 前必须通知 A/B/C 三个区域的负责人，并在 PR 中标明受影响模块、兼容期和迁移方式。
- 禁止由单个区域先改实现、后补约定，造成接口含义漂移。
- 任何破坏兼容性的改动都必须单独说明，并提供调用方迁移步骤。

## 5. 测试与验证

- 新功能至少包含成功路径、失败路径和关键边界条件测试。
- 解析、状态流转、幂等、用户隔离和回执等核心行为必须覆盖。
- 修复缺陷时，应先补充能够复现问题的测试，再修复实现。
- PR 描述中记录实际执行的测试命令和结果，不能只写“已测试”。

## 6. 数据与密钥安全

- 禁止提交数据库文件、日志、密钥、Cookie、Token、AppSecret、登录态截图、真实用户隐私和蓝 PC 运行数据。
- 禁止提交个人学习笔记、师徒工作台、群聊草稿、Agent 过程记录、与本项目无关的发布试验和本机抓屏/OCR 工具。
- 所有密钥和凭证只通过本机环境变量、部署环境或 GitHub Actions Secrets 注入。
- 不得在代码、README、Issue、PR、提交信息或日志中写入真实密钥值。
- 本地运行产生的数据应放在已忽略的目录中；如需共享样例数据，使用脱敏后的固定测试夹具。
- 提交前至少检查：

```powershell
git status --short
git diff --cached --stat
git diff --cached
```

重点确认暂存区中没有 `.env`、`*.db`、`__pycache__/`、`*.log`、密钥文件和含登录态的截图。

## 7. 提交规范

- 提交信息使用祈使句，清楚说明改动目的，例如 `Add correction idempotency contract test`。
- 不把多个无关改动塞进一个提交。
- 不提交生成缓存、编辑器临时文件或本地 IDE 配置。

## 8. 分支保护

仓库管理员应把 `main` 配置为保护分支，至少要求：

- 禁止直接 push；
- 合入前必须通过 CI 检查；
- 至少一名其他成员批准；
- 禁止强制 push；
- 合并后删除功能分支。

共享仓库为 `https://github.com/SSHOOTING/task-life-ai-assistant`。若当前 GitHub 账户或仓库计划不支持某条保护规则，应在项目记录中明确写出限制，不能把未配置的项目写成已配置。
