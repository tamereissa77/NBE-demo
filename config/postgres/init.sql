-- NBE demo database bootstrap. One schema per demo plus a shared audit log.
CREATE SCHEMA IF NOT EXISTS d1;
CREATE SCHEMA IF NOT EXISTS d2;
CREATE SCHEMA IF NOT EXISTS d3;
CREATE SCHEMA IF NOT EXISTS d4;
CREATE SCHEMA IF NOT EXISTS d5;
CREATE SCHEMA IF NOT EXISTS d6;
CREATE SCHEMA IF NOT EXISTS d7;
CREATE SCHEMA IF NOT EXISTS audit;

-- Every model call, tool call and human decision is written here ("Show the work" drawer).
CREATE TABLE IF NOT EXISTS audit.events (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    demo        TEXT NOT NULL,
    session_id  TEXT,
    kind        TEXT NOT NULL,          -- llm_call | tool_call | retrieval | guardrail | human_decision | ...
    actor       TEXT,                   -- model alias, tool name or reviewer
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    latency_ms  INTEGER
);
CREATE INDEX IF NOT EXISTS events_demo_ts ON audit.events (demo, ts DESC);
