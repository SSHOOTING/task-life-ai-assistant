# Documentation Index

Read these documents in order:

| Order | Document | What it answers |
|---|---|---|
| 1 | [PRD](PRD_v0.7.docx) | What the product must do and which product rules cannot be broken |
| 2 | [MVP technical specification](MVP_SPEC_v1.0.docx) | How the MVP is divided, implemented, connected, and accepted |
| 3 | [SPEC reading guide](spec-reading-guide.md) | A one-page orientation to the target architecture versus the current MVP |
| 4 | [WeChat integration notes](wechat-integration.md) | Local mock behavior, real-account prerequisites, and platform risks |
| 5 | [Acceptance cases and data-state baseline](acceptance-cases.md) | What each case must write to `raw_events` and `tasks`, and which cases pass or remain skipped |
| 6 | [Lead confirmation checklist](open-questions.md) | Plain-language data model, decisions that need confirmation, and their data-state impact |
| 7 | [CI/CD guide](ci-cd.md) | Pull-request checks, release builds, and deployment boundaries |

The PRD is the product source. The technical specification is the engineering baseline. When they conflict, visible product behavior follows the PRD, technical structure follows the specification, and the conflict must be recorded rather than resolved silently.

## Repository documentation rules

- Keep product requirements, engineering contracts, runbooks, and acceptance records here.
- Do not add personal study notes, agent working transcripts, group-chat drafts, login screenshots, or unrelated experiments.
- Put environment-specific host names, account identifiers, and credentials in local configuration or repository secrets.
