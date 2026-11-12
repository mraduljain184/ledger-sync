from core.events import Event
from core.hlc import HLC


def to_json(e):
    return {"id": e.id, "device": e.device, "hlc_wall": e.hlc.wall,
            "hlc_counter": e.hlc.counter, "hlc_device": e.hlc.device,
            "entry": e.entry, "op": e.op, "party": e.party,
            "amount": e.amount, "note": e.note, "base": e.base}


def from_json(d):
    return Event(id=d["id"], device=d["device"],
                 hlc=HLC(d["hlc_wall"], d["hlc_counter"], d["hlc_device"]),
                 entry=d["entry"], op=d["op"], party=d["party"],
                 amount=d["amount"], note=d["note"], base=d["base"])


class ApiBackend:
    """Talks to the FastAPI app. Baselines in Step 5 will be other backends."""

    def __init__(self, client):
        self.client = client

    def push(self, merchant, device, batch_id, events):
        body = {"merchant": merchant, "device": device, "batch_id": batch_id,
                "events": [to_json(e) for e in events]}
        r = self.client.post("/v1/sync", json=body, headers={"Idempotency-Key": batch_id})
        r.raise_for_status()
        return r.json()

    def pull(self, merchant, since):
        r = self.client.get("/v1/sync", params={"merchant": merchant, "since": since, "limit": 500})
        r.raise_for_status()
        data = r.json()
        return [from_json(d) for d in data["events"]], data["next"], data["more"]

    def state(self, merchant):
        r = self.client.get(f"/v1/state/{merchant}")
        r.raise_for_status()
        return r.json()