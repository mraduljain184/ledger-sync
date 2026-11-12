import pytest
from fastapi.testclient import TestClient

from server import db
from server.app import app
from sim.backend import ApiBackend
from sim.simulate import Config, Faults, run_merchant


@pytest.fixture
def client():
    with TestClient(app) as c:
        with db.pool.connection() as conn:
            conn.execute("TRUNCATE events, batches RESTART IDENTITY")
        yield c


class DroppingBackend(ApiBackend):
    """A deliberately broken server path: silently loses the last event of every batch."""
    def push(self, merchant, device, batch_id, events):
        return super().push(merchant, device, batch_id, events[:-1])


def test_nasty_network_still_converges(client):
    rough = Faults(p_req_lost=0.3, p_resp_lost=0.3, p_dup=0.3)
    res = run_merchant(ApiBackend(client), "t1", Config(ticks=200), rough, seed=1)
    assert res["events"] > 10
    assert res["lost_requests"] + res["lost_responses"] > 0   # faults really happened
    assert res["ok"], res


def test_checker_catches_a_server_that_loses_events(client):
    res = run_merchant(DroppingBackend(client), "t2", Config(ticks=200), Faults(), seed=1)
    assert res["lost"] > 0
    assert not res["ok"]


def test_same_seed_gives_same_run(client):
    def once():
        with db.pool.connection() as conn:
            conn.execute("TRUNCATE events, batches RESTART IDENTITY")
        r = run_merchant(ApiBackend(client), "t3", Config(ticks=150), Faults(), seed=7)
        return r["events"], r["conflicts"], r["attempts"]
    assert once() == once()