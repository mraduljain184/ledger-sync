import pytest
from fastapi.testclient import TestClient

from server import db
from server.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        with db.pool.connection() as conn:
            conn.execute("TRUNCATE events, batches RESTART IDENTITY")
        yield c


def ev(id, device, wall, entry, op, **kw):
    d = dict(id=id, device=device, hlc_wall=wall, hlc_counter=0,
             hlc_device=device, entry=entry, op=op)
    d.update(kw)
    return d


def push(client, merchant, device, batch_id, events):
    body = {"merchant": merchant, "device": device, "batch_id": batch_id, "events": events}
    return client.post("/v1/sync", json=body, headers={"Idempotency-Key": batch_id})


def test_retry_returns_same_response_and_adds_nothing(client):
    events = [ev("c1", "A", 100, "e1", "create", party="ramesh", amount=50000)]
    first = push(client, "m1", "A", "b1", events).json()
    second = push(client, "m1", "A", "b1", events).json()
    assert first == second
    assert first["accepted"] == 1
    assert client.get("/v1/state/m1").json()["events"] == 1


def test_same_event_in_a_new_batch_is_ignored(client):
    e = ev("c1", "A", 100, "e1", "create", party="ramesh", amount=50000)
    push(client, "m1", "A", "b1", [e])
    r = push(client, "m1", "A", "b2", [e]).json()
    assert r["accepted"] == 0 and r["duplicates"] == 1


def test_key_must_match_batch_id(client):
    body = {"merchant": "m1", "device": "A", "batch_id": "b1", "events": []}
    r = client.post("/v1/sync", json=body, headers={"Idempotency-Key": "other"})
    assert r.status_code == 400


def test_concurrent_edits_make_one_conflict(client):
    push(client, "m1", "A", "b1", [ev("c1", "A", 90, "e1", "create", party="ramesh", amount=50000)])
    push(client, "m1", "A", "b2", [ev("a1", "A", 100, "e1", "edit_amount", amount=45000, base="c1")])
    push(client, "m1", "B", "b3", [ev("b1", "B", 103, "e1", "edit_amount", amount=48000, base="c1")])

    st = client.get("/v1/state/m1").json()
    assert st["balances"]["ramesh"] == 48000
    assert st["conflicts"] == 1
    assert len(client.get("/v1/conflicts/m1").json()) == 1


def test_delivery_order_does_not_change_state(client):
    a = ev("c1", "A", 90, "e1", "create", party="ramesh", amount=50000)
    b = ev("a1", "A", 100, "e1", "edit_amount", amount=45000, base="c1")
    c = ev("b1", "B", 103, "e1", "edit_amount", amount=48000, base="c1")

    def run(order, prefix):
        with db.pool.connection() as conn:
            conn.execute("TRUNCATE events, batches RESTART IDENTITY")
        for i, e in enumerate(order):
            push(client, "m1", e["device"], f"{prefix}-{i}", [e])   # one event per batch
        st = client.get("/v1/state/m1").json()
        assert st["events"] == 3
        return st["digest"]

    assert run([a, b, c], "fwd") == run([c, b, a], "rev")


def test_pull_uses_cursor(client):
    push(client, "m1", "A", "b1", [
        ev("c1", "A", 90, "e1", "create", party="ramesh", amount=100),
        ev("c2", "A", 91, "e2", "create", party="sita", amount=200),
    ])
    first = client.get("/v1/sync", params={"merchant": "m1", "since": 0}).json()
    assert len(first["events"]) == 2
    again = client.get("/v1/sync", params={"merchant": "m1", "since": first["next"]}).json()
    assert again["events"] == []