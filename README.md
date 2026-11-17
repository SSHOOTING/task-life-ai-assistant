# Task Life AI Assistant

Task Life AI Assistant is the English repository name for the product described in the PRD as “连接任务与生活的 AI 个人助手”.

The MVP is a local-first assistant that accepts one natural-language message, preserves the original text, and extracts traceable task, progress, habit, and life records. The current implementation is a runnable single-process MVP plus the contracts and deployment scripts needed for the three-person A/B/C delivery model.

## Quick start

Requirements: Python 3.10 or newer. The MVP runtime uses only the Python standard library.

```powershell
git clone https://github.com/SSHOOTING/task-life-ai-assistant.git
cd task-life-ai-assistant

$env:LLM_MODE = "mock"
python -m unittest discover -s mvp/tests -v
python -m mvp.app --port 18765
```

Open `http://127.0.0.1:18765`.

The fixed demo message is:

```text
今天背完单词了，论文开头也改了，跟朋友聊完没那么焦虑了。
```

Expected result: one raw event and two task records. The life reflection remains in the original text and does not create an emotion or task record.

## Current status

| Area | Status |
|---|---|
| H5 and local HTTP MVP | Runnable in one process on port `18765` |
| Data model | `raw_events + tasks`; corrections are append-only raw events |
| Baseline tests | 18 tests pass with `LLM_MODE=mock` |
| WeChat callback | Local mock only; no real account, public HTTPS callback, or customer-service delivery |
| LLM | OpenCode-compatible parser plus coach; Mock mode is the deterministic default |
| Acceptance cases | TC-001 passes; TC-002 to TC-014 retain explicit skip reasons |
| Deployment | Blue PC scripts and GitHub Actions workflow are present; host details and credentials stay outside Git |
| A/B/C service split | Logical responsibility split only; current runtime is one process |

## Documentation

1. [Documentation index](docs/README.md)
2. [Product requirements](docs/PRD_v0.7.docx)
3. [MVP technical specification](docs/MVP_SPEC_v1.0.docx)
4. [SPEC reading guide](docs/spec-reading-guide.md)
5. [WeChat integration notes](docs/wechat-integration.md)
6. [Acceptance case matrix](docs/acceptance-cases.md)
7. [Open product questions](docs/open-questions.md)
8. [CI/CD guide](docs/ci-cd.md)

## Repository map

| Path | Purpose |
|---|---|
| `mvp/` | Runnable MVP, H5, parser, coach, tests, and local WeChat adapter |
| `docs/` | PRD, technical specification, decision log, and delivery guidance |
| `contracts/` | Shared API and JSON-schema contract baseline |
| `deploy/bluepc/` | Blue PC deployment, health check, and rollback scripts |
| `ci/` | Deterministic release build and deployment smoke tooling |
| `.github/workflows/` | Pull-request CI and manual Blue PC deployment workflow |
| `tests/acceptance/` | P0 acceptance evidence and skipped next-stage skeletons |

## Team workflow

Do not commit directly to `main`.

```powershell
git checkout main
git pull --ff-only
git checkout -b feature/<area>-<topic>
```

Open a pull request when the change is ready. One PR should solve one reviewable problem. A, B, and C must not cross each other's data boundary: A owns channel/UI, B owns orchestration/coach, and C owns parsing/data.

Before the lead confirms the open questions, only read, audit, and record questions. Do not guess new business cases or change the data model.

## Local quality checks

```powershell
$env:LLM_MODE = "mock"
python -m compileall -q mvp ci
python -m unittest discover -s mvp/tests -v
python -m unittest discover -s tests/acceptance -v
```

Expected:

- MVP tests: 18 passing.
- Acceptance suite: 1 passing and 13 explicitly skipped until the lead clarifies scope and the remaining interfaces exist.

## Deployment

Deployment scripts target a separately managed Windows host. Host names, SSH credentials, Tailscale addresses, and environment-specific paths belong in local configuration or GitHub Actions Secrets, not in this repository. See [the deployment guide](deploy/bluepc/README.md) and [the CI/CD guide](docs/ci-cd.md).

## Security

Do not commit database files, logs, `.env` files, API keys, cookies, WeChat secrets, screenshots containing login state or personal data, local screen-capture utilities, personal study notes, or unrelated publication experiments.

## License

MIT. See [LICENSE](LICENSE).
