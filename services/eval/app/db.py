"""Postgres storage for the Arabic gate (schema `eval`)."""
import psycopg
from psycopg.rows import dict_row

from nbe_core import settings

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS eval;
CREATE TABLE IF NOT EXISTS eval.outputs (
    id          TEXT PRIMARY KEY,               -- opaque id shown to scorers instead of the model name
    item_id     TEXT NOT NULL,
    alias       TEXT NOT NULL,                  -- gateway alias, e.g. workhorse
    model       TEXT,                           -- model that actually answered
    text        TEXT,
    tool_calls  JSONB DEFAULT '[]'::jsonb,
    latency_ms  INTEGER,
    completion_tokens INTEGER,
    tokens_per_s REAL,
    auto_pass   BOOLEAN,                        -- NULL when the item has no automatic check
    auto_detail TEXT,
    judge       JSONB,                          -- {correctness, arabic, format, rationale, judge_model}
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (item_id, alias)
);
CREATE TABLE IF NOT EXISTS eval.human_scores (
    scorer      TEXT NOT NULL,
    output_id   TEXT NOT NULL REFERENCES eval.outputs(id) ON DELETE CASCADE,
    correctness SMALLINT CHECK (correctness BETWEEN 1 AND 5),
    arabic      SMALLINT CHECK (arabic BETWEEN 1 AND 5),
    format      SMALLINT CHECK (format BETWEEN 1 AND 5),
    note        TEXT,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (scorer, output_id)
);
"""


def connect():
    return psycopg.connect(settings.postgres_dsn, row_factory=dict_row, autocommit=True)


def init() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
