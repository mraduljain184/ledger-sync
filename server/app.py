import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, Header, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from core.events import Event
from core.hlc import HLC
from core.merge import balance, build_state, digest, entries_digest
from server import db

MAX_DRIFT_MS = 24 * 60 * 60 * 1000   # events from more than a day in the future are suspect


@asynccontextmanager
async def lifespan(app):
    db.open_pool()
    db.init_schema()
    yield
    db.close_pool()


app = FastAPI(title="Ledger sync", lifespan=lifespan)


class EventIn(BaseModel):
    id: str
    device: str
    hlc_wall: int
    hlc_counter: int
    hlc_device: str
    entry: str
    op: Literal["create", "edit_amount", "edit_note", "delete"]
    party: str = ""
    amount: int = 0
    note: str = ""
    base: Optional[str] = None


class BatchIn(BaseModel):
    merchant: str
    device: str
    batch_id: str
    events: list[EventIn] = Field(max_length=500)


def to_event(r):
    return Event(
        id=r["event_id"], device=r["device"],
        hlc=HLC(r["hlc_wall"], r["hlc_counter"], r["hlc_device"]),
        entry=r["entry"], op=r["op"], party=r["party"],
        amount=r["amount"], note=r["note"], base=r["base"],
    )


def to_dict(r):
    return {
        "id": r["event_id"], "device": r["device"],
        "hlc_wall": r["hlc_wall"], "hlc_counter": r["hlc_counter"],
        "hlc_device": r["hlc_device"], "entry": r["entry"], "op": r["op"],
        "party": r["party"], "amount": r["amount"], "note": r["note"],
        "base": r["base"], "server_seq": r["server_seq"],
        "clock_suspect": r["clock_suspect"],
    }


def load_events(cur, merchant):
    cur.execute("SELECT * FROM events WHERE merchant = %s ORDER BY server_seq", (merchant,))
    return [to_event(r) for r in cur.fetchall()]


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/sync")
def push(batch: BatchIn, idempotency_key: str = Header(...)):
    if idempotency_key != batch.batch_id:
        raise HTTPException(400, "Idempotency-Key must equal batch_id")
    now = int(time.time() * 1000)

    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            # one writer per merchant at a time
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (batch.merchant,))

            cur.execute("SELECT response FROM batches WHERE batch_id = %s", (batch.batch_id,))
            seen = cur.fetchone()
            if seen:
                return seen["response"]

            accepted = duplicates = 0
            for e in batch.events:
                cur.execute(
                    """INSERT INTO events
                         (event_id, merchant, device, hlc_wall, hlc_counter, hlc_device,
                          entry, op, party, amount, note, base, clock_suspect)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (event_id) DO NOTHING""",
                    (e.id, batch.merchant, e.device, e.hlc_wall, e.hlc_counter,
                     e.hlc_device, e.entry, e.op, e.party, e.amount, e.note, e.base,
                     e.hlc_wall > now + MAX_DRIFT_MS),
                )
                if cur.rowcount == 1:
                    accepted += 1
                else:
                    duplicates += 1

            cur.execute("SELECT COALESCE(MAX(server_seq), 0) AS s FROM events WHERE merchant = %s",
                        (batch.merchant,))
            response = {
                "batch_id": batch.batch_id,
                "accepted": accepted,
                "duplicates": duplicates,
                "server_seq": cur.fetchone()["s"],
            }
            cur.execute("INSERT INTO batches (batch_id, response) VALUES (%s, %s)",
                        (batch.batch_id, Jsonb(response)))
    return response


@app.get("/v1/sync")
def pull(merchant: str, since: int = 0, limit: int = 500):
    limit = min(limit, 1000)
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM events
                   WHERE merchant = %s AND server_seq > %s
                   ORDER BY server_seq LIMIT %s""",
                (merchant, since, limit))
            rows = cur.fetchall()
    return {
        "events": [to_dict(r) for r in rows],
        "next": rows[-1]["server_seq"] if rows else since,
        "more": len(rows) == limit,
    }


@app.get("/v1/state/{merchant}")
def state(merchant: str):
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            events = load_events(cur, merchant)
    st = build_state(events)
    parties = sorted({x.party for x in st.entries.values()})
    return {
        "events": len(events),
        "digest": digest(st),
        "entries_digest": entries_digest(st),
        "balances": {p: balance(st, p) for p in parties},
        "conflicts": len(st.conflicts),
    }


@app.get("/v1/conflicts/{merchant}")
def conflicts(merchant: str):
    with db.pool.connection() as conn:
        with conn.cursor() as cur:
            events = load_events(cur, merchant)
    st = build_state(events)
    return [{"entry": c.entry, "kind": c.kind, "earlier": c.earlier, "later": c.later}
            for c in st.conflicts]