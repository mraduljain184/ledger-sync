import pytest
from fastapi.testclient import TestClient

from server import db
from server.app import app
from sim.backend import ApiBackend
from sim.baselines import SYSTEMS, ModelServer
from sim.simulate import Config, Faults, run_merchant


@pytest.fixture
def client():
    with TestClient(app) as c:
        with db.pool.connection() as conn:
            conn.execute("TRUNCATE events, batches RESTART IDENTITY")
        yield c


def test_naive_server_double_counts_under_retries():
    rough = Faults(p_req_lost=0.2, p_resp_lost=0.3, p_dup=0.3)
    r = run_merchant(ModelServer(**SYSTEMS["S0"]), "t", Config(ticks=250, hybrid=False), rough, seed=3)
    assert r["dup_rows"] > 0
    assert not r["ok"]


def test_batch_key_alone_is_not_enough():
    f = Faults(p_req_lost=0, p_resp_lost=0.5, p_dup=0, p_rebatch=1.0)
    s1 = run_merchant(ModelServer(**SYSTEMS["S1"]), "t", Config(ticks=250, hybrid=False), f, seed=4)
    a2 = run_merchant(ModelServer(**SYSTEMS["A2"]), "t", Config(ticks=250), f, seed=4)
    assert s1["dup_rows"] > 0
    assert a2["dup_rows"] == 0 and a2["ok"]


def test_plain_clocks_cause_inversions_but_hlc_does_not():
    cfg = dict(ticks=400, p_conc=0.5, p_edit=0.5)
    plain = hybrid = 0
    for seed in range(8):
        plain += run_merchant(ModelServer(**SYSTEMS["A1"]), "t",
                              Config(hybrid=False, **cfg), Faults(), seed=seed)["inversions"]
        hybrid += run_merchant(ModelServer(**SYSTEMS["A2"]), "t",
                               Config(**cfg), Faults(), seed=seed)["inversions"]
    assert hybrid == 0       # a hybrid clock can never stamp an edit before what it saw
    assert plain > 0         # plain clocks with skewed phones sometimes do

def test_model_of_s2_matches_the_real_api(client):
    cfg = Config(ticks=200)
    a = run_merchant(ApiBackend(client), "x1", cfg, Faults(), seed=5)
    b = run_merchant(ModelServer(), "x1", cfg, Faults(), seed=5)
    assert a["ok"] and b["ok"]
    assert (a["events"], a["conflicts"], a["conflicts_flagged"]) == \
           (b["events"], b["conflicts"], b["conflicts_flagged"])