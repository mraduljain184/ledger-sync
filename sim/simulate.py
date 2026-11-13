import random
import time
from collections import Counter
from dataclasses import dataclass

from core.merge import balance, build_state, digest, entries_digest
from sim.device import Device

PARTIES = ["ramesh", "sita", "kumar", "meena", "gopal", "anil"]
NOTES = ["advance", "festival order", "returned", "partial", "weekly"]


@dataclass
class Config:
    devices: int = 3
    ticks: int = 300          # one tick = one virtual minute
    p_act: float = 0.25       # chance a phone's user records something each tick
    p_edit: float = 0.20      # share of actions that edit an existing entry
    p_conc: float = 0.05      # chance an edit targets an entry another phone created
    mean_offline: float = 30  # ticks
    mean_online: float = 60
    sync_every: int = 5
    batch_size: int = 50
    hybrid: bool = True       # phones use hybrid logical clocks (False = plain wall clock)


@dataclass
class Faults:
    p_req_lost: float = 0.075
    p_resp_lost: float = 0.075
    p_dup: float = 0.10
    p_rebatch: float = 0.5
    reorder: bool = True
    max_skew_ms: int = 300_000


def act(dev, rng, cfg, creator):
    live = [x for x in dev.state().entries.values() if not x.deleted]
    if live and rng.random() < cfg.p_edit:
        others = [x for x in live if creator[x.id] != dev.name]
        mine = [x for x in live if creator[x.id] == dev.name]
        pool = others if (others and rng.random() < cfg.p_conc) else (mine or others)
        x = rng.choice(pool)
        r = rng.random()
        if r < 0.6:
            return dev.edit_amount(x.id, rng.randint(1, 500) * 100)
        if r < 0.9:
            return dev.edit_note(x.id, rng.choice(NOTES))
        return dev.delete(x.id)
    amount = rng.choice([-1, 1]) * rng.randint(1, 500) * 100
    e = dev.create(rng.choice(PARTIES), amount)
    creator[e.entry] = dev.name
    return e


def sync_device(dev, backend, faults, rng, stats, batch_size):
    dev.make_batches(batch_size)
    ids = list(dev.pending)
    if faults.reorder:
        rng.shuffle(ids)
    for bid in ids:
        events = dev.pending[bid]
        stats["attempts"] += 1
        if rng.random() < faults.p_req_lost:
            stats["lost_requests"] += 1
            continue
        backend.push(dev.merchant, dev.name, bid, events)
        if rng.random() < faults.p_dup:
            stats["dup_deliveries"] += 1
            backend.push(dev.merchant, dev.name, bid, events)
        if rng.random() < faults.p_resp_lost:
            stats["lost_responses"] += 1
            if rng.random() < faults.p_rebatch:
                dev.unsent = dev.pending.pop(bid) + dev.unsent
                stats["rebatched"] += 1
            continue
        del dev.pending[bid]

    since = dev.cursor
    while True:
        events, nxt, more = backend.pull(dev.merchant, since)
        dev.learn(events)
        since = dev.cursor = nxt
        if not more:
            break


def fetch_all(backend, merchant):
    ids, rows, since = set(), 0, 0
    while True:
        events, since, more = backend.pull(merchant, since)
        rows += len(events)
        ids |= {e.id for e in events}
        if not more:
            return ids, rows


def run_merchant(backend, merchant, cfg, faults, seed):
    rng = random.Random(seed)
    now = [1_760_000_000_000]
    devs = []
    for i in range(cfg.devices):
        skew = rng.randint(-faults.max_skew_ms, faults.max_skew_ms)
        devs.append(Device(merchant, f"{merchant}-d{i}", (lambda s=skew: now[0] + s), rng, cfg.hybrid))

    creator, created, stats = {}, {}, Counter()
    t0 = time.perf_counter()

    for tick in range(cfg.ticks):
        now[0] += 60_000
        for i, dev in enumerate(devs):
            if dev.online and rng.random() < 1 / cfg.mean_online:
                dev.online = False
            elif not dev.online and rng.random() < 1 / cfg.mean_offline:
                dev.online = True
            if rng.random() < cfg.p_act:
                e = act(dev, rng, cfg, creator)
                created[e.id] = e
            if dev.online and (tick + i) % cfg.sync_every == 0:
                sync_device(dev, backend, faults, rng, stats, cfg.batch_size)

    clean = Faults(0, 0, 0, 0, False, 0)
    for _ in range(3):
        for dev in devs:
            dev.online = True
            sync_device(dev, backend, clean, rng, Counter(), cfg.batch_size)

    # ---- the oracle ----
    oracle = build_state(created.values())
    want = digest(oracle)
    want_entries = entries_digest(oracle)
    server = backend.state(merchant)
    server_ids, server_rows = fetch_all(backend, merchant)
    parties = sorted({x.party for x in oracle.entries.values()})
    want_balances = {p: balance(oracle, p) for p in parties}

    lost = len(set(created) - server_ids)                        # I1: nothing lost
    dup_rows = server_rows - len(server_ids)                     # repeated rows stored
    extra = len(server_ids - set(created)) + dup_rows            # I2: nothing doubled or invented
    state_ok = server["entries_digest"] == want_entries          # I3: server state equals the oracle
    devices_ok = all(digest(d.state()) == want for d in devs)    # every phone equals the oracle
    balances_ok = server["balances"] == want_balances            # I4: balances equal the oracle's

    n = len(created)
    return {
        "events": n,
        "server_events": server["events"],
        "lost": lost,
        "extra": extra,
        "dup_rows": dup_rows,
        "state_ok": state_ok,
        "devices_ok": devices_ok,
        "converged": state_ok and devices_ok,
        "balances_ok": balances_ok,
        "ok": lost == 0 and extra == 0 and state_ok and devices_ok and balances_ok,
        "conflicts": len(oracle.conflicts),
        "conflicts_flagged": server["conflicts"],
        "conflict_rate": round(100 * len(oracle.conflicts) / n, 3) if n else 0.0,
        "inversions": sum(d.inversions for d in devs),
        "based_edits": sum(d.based_edits for d in devs),
        "attempts": stats["attempts"],
        "lost_requests": stats["lost_requests"],
        "lost_responses": stats["lost_responses"],
        "dup_deliveries": stats["dup_deliveries"],
        "rebatched": stats["rebatched"],
        "seconds": round(time.perf_counter() - t0, 2),
    }