"""Mock bank APIs for the NBE demos (PLAN.md §4 D4). Every banking action in the demos hits
this service and nothing else; it lives on the internal network only.

OTP codes are returned in the response on purpose: this is a demo, and the D4 tool-call lane
shows the code so the audience can follow the flow.
"""
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import Header, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel

from nbe_core import create_app, settings
from nbe_core import locale as L
from app.seed import customers

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS bank;
CREATE TABLE IF NOT EXISTS bank.customers (id TEXT PRIMARY KEY, name_ar TEXT, name_en TEXT, phone TEXT, city TEXT);
CREATE TABLE IF NOT EXISTS bank.accounts (customer_id TEXT PRIMARY KEY REFERENCES bank.customers, balance NUMERIC(14,2), currency TEXT DEFAULT 'EGP');
CREATE TABLE IF NOT EXISTS bank.cards (id SERIAL PRIMARY KEY, customer_id TEXT REFERENCES bank.customers, last4 TEXT, type TEXT,
    status TEXT DEFAULT 'active', block_reason TEXT, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS bank.otps (customer_id TEXT, code TEXT, expires_at TIMESTAMPTZ, used BOOLEAN DEFAULT false);
CREATE TABLE IF NOT EXISTS bank.sessions (token TEXT PRIMARY KEY, customer_id TEXT, expires_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS bank.tickets (id TEXT PRIMARY KEY, customer_id TEXT, category TEXT, description TEXT,
    channel TEXT, status TEXT DEFAULT 'open', created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS bank.handoffs (id TEXT PRIMARY KEY, customer_id TEXT, reason TEXT, summary TEXT,
    status TEXT DEFAULT 'waiting', created_at TIMESTAMPTZ DEFAULT now());
"""


def db():
    return psycopg.connect(settings.postgres_dsn, row_factory=dict_row, autocommit=True)


def reset() -> int:
    """Drop all demo state and reseed. Used by `make demo-reset` between audiences."""
    seed = customers()
    with db() as conn:
        conn.execute("DROP SCHEMA IF EXISTS bank CASCADE")
        conn.execute(SCHEMA)
        for c in seed:
            conn.execute("INSERT INTO bank.customers VALUES (%s,%s,%s,%s,%s)",
                         (c["id"], c["name_ar"], c["name_en"], c["phone"], c["city"]))
            conn.execute("INSERT INTO bank.accounts (customer_id, balance, currency) VALUES (%s,%s,%s)", (c["id"], c["balance"], L.CURRENCY))
            for card in c["cards"]:
                conn.execute("INSERT INTO bank.cards (customer_id, last4, type) VALUES (%s,%s,%s)",
                             (c["id"], card["last4"], card["type"]))
    return len(seed)


@asynccontextmanager
async def lifespan(_app):
    with db() as conn:
        exists = conn.execute("SELECT to_regclass('bank.customers') AS t").fetchone()["t"]
    if not exists:
        reset()
    yield


app = create_app("mockbank", "Mock bank APIs", phase="platform")
app.router.lifespan_context = lifespan


def _customer(conn, customer_id: str) -> dict:
    row = conn.execute("SELECT * FROM bank.customers WHERE id=%s", (customer_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"unknown customer {customer_id}")
    return row


def _session(conn, token: str | None) -> str:
    if not token:
        raise HTTPException(401, "OTP verification required (X-Session header missing)")
    row = conn.execute("SELECT customer_id FROM bank.sessions WHERE token=%s AND expires_at > now()", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "session expired or invalid; verify OTP again")
    return row["customer_id"]


class OtpSend(BaseModel):
    customer_id: str


class OtpVerify(BaseModel):
    customer_id: str
    code: str


class BlockCard(BaseModel):
    reason: str = "lost"   # lost | stolen | fraud | customer_request


class TicketIn(BaseModel):
    customer_id: str
    category: str
    description: str
    channel: str = "virtual_agent"


class HandoffIn(BaseModel):
    customer_id: str
    reason: str
    summary: str = ""


@app.get("/customers")
def list_customers():
    with db() as conn:
        return conn.execute("SELECT id, name_ar, name_en, city FROM bank.customers ORDER BY id").fetchall()


@app.post("/otp/send")
def otp_send(body: OtpSend):
    code = f"{secrets.randbelow(10_000):04d}"
    with db() as conn:
        c = _customer(conn, body.customer_id)
        conn.execute("UPDATE bank.otps SET used=true WHERE customer_id=%s", (body.customer_id,))
        conn.execute("INSERT INTO bank.otps VALUES (%s,%s,%s,false)",
                     (body.customer_id, code, datetime.now(timezone.utc) + timedelta(minutes=5)))
    return {"sent": True, "to": c["phone"], "expires_in_s": 300, "demo_code": code}


@app.post("/otp/verify")
def otp_verify(body: OtpVerify):
    with db() as conn:
        row = conn.execute("SELECT 1 FROM bank.otps WHERE customer_id=%s AND code=%s AND NOT used AND expires_at > now()",
                           (body.customer_id, body.code.strip())).fetchone()
        if not row:
            return {"verified": False}
        conn.execute("UPDATE bank.otps SET used=true WHERE customer_id=%s", (body.customer_id,))
        token = uuid.uuid4().hex
        conn.execute("INSERT INTO bank.sessions VALUES (%s,%s,%s)",
                     (token, body.customer_id, datetime.now(timezone.utc) + timedelta(minutes=15)))
    return {"verified": True, "session": token, "expires_in_s": 900}


@app.get("/cards")
def cards(x_session: str | None = Header(default=None)):
    with db() as conn:
        cid = _session(conn, x_session)
        return conn.execute("SELECT id, last4, type, status, block_reason FROM bank.cards WHERE customer_id=%s ORDER BY id",
                            (cid,)).fetchall()


@app.post("/cards/{last4}/block")
def block_card(last4: str, body: BlockCard, x_session: str | None = Header(default=None)):
    with db() as conn:
        cid = _session(conn, x_session)
        row = conn.execute("UPDATE bank.cards SET status='blocked', block_reason=%s, updated_at=now() "
                           "WHERE customer_id=%s AND last4=%s RETURNING id, last4, type, status, block_reason",
                           (body.reason, cid, last4)).fetchone()
        if not row:
            raise HTTPException(404, f"no card ending {last4} for this customer")
    return row


@app.post("/cards/{last4}/unblock")
def unblock_card(last4: str, x_session: str | None = Header(default=None)):
    with db() as conn:
        cid = _session(conn, x_session)
        row = conn.execute("UPDATE bank.cards SET status='active', block_reason=NULL, updated_at=now() "
                           "WHERE customer_id=%s AND last4=%s RETURNING id, last4, type, status", (cid, last4)).fetchone()
        if not row:
            raise HTTPException(404, f"no card ending {last4} for this customer")
    return row


@app.get("/balance")
def balance(x_session: str | None = Header(default=None)):
    with db() as conn:
        cid = _session(conn, x_session)
        return conn.execute("SELECT customer_id, balance, currency FROM bank.accounts WHERE customer_id=%s", (cid,)).fetchone()


@app.post("/tickets")
def create_ticket(body: TicketIn):
    tid = f"T-{datetime.now():%y%m%d}-{secrets.randbelow(100_000):05d}"
    with db() as conn:
        _customer(conn, body.customer_id)
        return conn.execute("INSERT INTO bank.tickets (id, customer_id, category, description, channel) "
                            "VALUES (%s,%s,%s,%s,%s) RETURNING *",
                            (tid, body.customer_id, body.category, body.description, body.channel)).fetchone()


@app.get("/tickets")
def list_tickets():
    with db() as conn:
        return conn.execute("SELECT * FROM bank.tickets ORDER BY created_at DESC LIMIT 100").fetchall()


@app.post("/handoff")
def handoff(body: HandoffIn):
    hid = f"H-{secrets.randbelow(100_000):05d}"
    with db() as conn:
        _customer(conn, body.customer_id)
        return conn.execute("INSERT INTO bank.handoffs (id, customer_id, reason, summary) VALUES (%s,%s,%s,%s) RETURNING *",
                            (hid, body.customer_id, body.reason, body.summary)).fetchone()


@app.get("/handoffs")
def list_handoffs():
    with db() as conn:
        return conn.execute("SELECT * FROM bank.handoffs ORDER BY created_at DESC LIMIT 100").fetchall()


@app.post("/admin/reset")
def admin_reset():
    return {"reset": True, "customers": reset()}
