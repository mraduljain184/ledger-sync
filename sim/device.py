import uuid

from core.events import Event, CREATE, EDIT_AMOUNT, EDIT_NOTE, DELETE
from core.hlc import Clock
from core.merge import build_state


def new_uuid(rng):
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


class Device:
    def __init__(self, merchant, name, now_fn, rng, hybrid=True):
        self.merchant = merchant
        self.name = name
        self.clock = Clock(name, now_fn, hybrid)
        self.rng = rng
        self.log = {}
        self.unsent = []
        self.pending = {}
        self.cursor = 0
        self.online = True
        self.inversions = 0     # edits stamped earlier than the event they were based on
        self.based_edits = 0    # edits that were based on an earlier event
        self._state = None

    def state(self):
        if self._state is None:
            self._state = build_state(self.log.values())
        return self._state

    def _emit(self, **kw):
        e = Event(id=new_uuid(self.rng), device=self.name, hlc=self.clock.tick(), **kw)
        if e.base is not None:
            self.based_edits += 1
            prev = self.log.get(e.base)
            if prev is not None and not e.hlc > prev.hlc:
                self.inversions += 1
        self.log[e.id] = e
        self.unsent.append(e)
        self._state = None
        return e

    def create(self, party, amount):
        return self._emit(entry=new_uuid(self.rng), op=CREATE, party=party, amount=amount)

    def edit_amount(self, entry, amount):
        base = self.state().amount_winner.get(entry)
        return self._emit(entry=entry, op=EDIT_AMOUNT, amount=amount, base=base)

    def edit_note(self, entry, note):
        return self._emit(entry=entry, op=EDIT_NOTE, note=note)

    def delete(self, entry):
        base = self.state().last.get(entry)
        return self._emit(entry=entry, op=DELETE, base=base)

    def learn(self, events):
        for e in events:
            if e.id not in self.log:
                self.log[e.id] = e
                self.clock.observe(e.hlc)
                self._state = None

    def make_batches(self, size):
        while self.unsent:
            chunk, self.unsent = self.unsent[:size], self.unsent[size:]
            self.pending[new_uuid(self.rng)] = chunk