# Shared Contracts

This directory is the source of truth for interfaces shared by A, B, and C. The specification describes the target contract; the current MVP still runs the responsibilities in one process.

## Boundary map

| Boundary | Contract | Current state |
|---|---|---|
| A to B | `POST /internal/v1/turns` with `TurnRequest` and `TurnResponse` | Target contract; local MVP exposes the external `/api/v1/turns` adapter |
| B to C | `POST /internal/v1/ingest` with `IngestRequest` and `IngestResult` | Target contract; current pipeline calls the parser and data layer directly |
| C to database | `raw_events + tasks` schema | Implemented in `mvp/schema.sql` |
| External H5 | `/api/v1/turns`, `/api/v1/tasks`, `/api/v1/corrections`, `/api/v1/events/{event_id}` | Implemented |
| External WeChat | `GET/POST /wechat/callback` | Local mock implemented; real signature and customer-service delivery are not connected |

## Change rule

Change the shared contract before changing an implementation. A contract PR must name the affected owners, compatibility impact, and migration path. Do not add a new shared field in only one service.

The machine-readable OpenAPI file is `openapi.yaml`. JSON examples in the specification remain the authoritative business examples until the first generated contract tests are added.

