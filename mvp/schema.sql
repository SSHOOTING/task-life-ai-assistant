PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS raw_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('h5', 'wechat')),
    source_message_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('utterance', 'correction', 'clarification')),
    content TEXT NOT NULL,
    related_event_id TEXT,
    target_record_id TEXT,
    parse_status TEXT NOT NULL CHECK (parse_status IN ('received', 'parsed', 'failed')),
    parse_result_json TEXT,
    response_payload_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, source, source_message_id),
    FOREIGN KEY (related_event_id) REFERENCES raw_events(event_id),
    FOREIGN KEY (target_record_id) REFERENCES tasks(record_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_events_user_created
    ON raw_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_events_parse_status
    ON raw_events(parse_status);

CREATE TABLE IF NOT EXISTS tasks (
    record_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('task', 'task_progress', 'daily_task')),
    title TEXT,
    content TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'in_progress', 'done', 'cancelled', 'revoked', 'active')
    ),
    occurred_on TEXT,
    due_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_event_id) REFERENCES raw_events(event_id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_occurred
    ON tasks(user_id, occurred_on);
CREATE INDEX IF NOT EXISTS idx_tasks_user_status
    ON tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_source_event
    ON tasks(source_event_id);

