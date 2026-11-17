# MVP per MVP_SPEC_v1.0

This implementation follows the two-table baseline in `../docs/MVP_SPEC_v1.0.docx`:

- `raw_events`: append-only user content, event type, parse status, parse result, and cached response;
- `tasks`: current task state for `task`, `task_progress`, and `daily_task`;
- life reflection stays in the raw utterance and does not create a task row;
- corrections are appended as `raw_events(event_type='correction')`, not a third table.

## Run

```powershell
python -m mvp.app --demo
python -m unittest discover -s mvp/tests -v
python -m mvp.app --port 18765
```

Open <http://127.0.0.1:18765>. `--demo` resets the local database so stale
schema and old records cannot affect a demo run. The HTTP server keeps its
database by default; pass `--reset-db` only when an explicit reset is intended.

## Local WeChat mock

Set a local-only random verification token before starting the service:

```powershell
$env:WECHAT_TOKEN = "<local random value>"
python -m mvp.app --port 18765
```

The mock adapter exposes `GET/POST /wechat/callback`, parses plaintext text,
voice `Recognition`, and the `TODAY` menu event, then maps `FromUserName` and
`MsgId` to the existing `user_id` and `source_message_id`. It reuses the
existing pipeline and idempotency behavior. See
[`../docs/wechat-integration.md`](../docs/wechat-integration.md) for local requests, real
account prerequisites, secret handling, and platform risks.

## LLM configuration

The key is read only from `OPENCODE_API_KEY`. It is never stored in this repo,
written to logs, or returned in API errors.

```powershell
$env:LLM_MODE = "opencode"
$env:OPENCODE_GO_MODEL = "hy4-flash-free"
$env:OPENCODE_GO_FALLBACK_MODEL = "longcat-2.5-free"
python -m mvp.app --demo
```

The C parser prompt explicitly describes its own module boundary and the
boundaries of A (channel/UI), B (orchestration/coach), and C (parsing/data).
It returns exactly:

```json
{"records": [], "clarification": null}
```

The B coach prompt is separate. It can only produce advice text; it cannot write
tasks. If the coach fails, the fixed receipt and task write remain valid.

