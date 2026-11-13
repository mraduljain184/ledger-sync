from core.events import CREATE, EDIT_AMOUNT, EDIT_NOTE, DELETE
from core.merge import Entry, digest_rows

# hybrid = do the phones use hybrid logical clocks (True) or plain wall clocks (False)
SYSTEMS = {
    "S0": dict(batch_idem=False, event_dedup=False, order="wall", conflicts=False, hybrid=False),
    "S1": dict(batch_idem=True,  event_dedup=False, order="wall", conflicts=False, hybrid=False),
    "A1": dict(batch_idem=True,  event_dedup=True,  order="wall", conflicts=True,  hybrid=False),
    "A2": dict(batch_idem=True,  event_dedup=True,  order="hlc",  conflicts=False, hybrid=True),
    "A3": dict(batch_idem=True,  event_dedup=False, order="hlc",  conflicts=True,  hybrid=True),
}


def fold(rows, order, detect, allow_dup):
    """Replay stored rows. With allow_dup=True a repeated create adds a second entry,
    which is what a server without event-level dedup would do."""
    if order == "wall":
        key = lambda r: (r[1].hlc.wall, r[0])
    else:
        key = lambda r: (r[1].hlc, r[0])
    entries, winner, last, flagged = {}, {}, {}, 0

    for _, e in sorted(rows, key=key):
        if e.op == CREATE:
            if e.entry in entries and not allow_dup:
                continue
            entries.setdefault(e.entry, []).append(Entry(e.entry, e.party, e.amount, e.note))
            winner.setdefault(e.entry, e.id)
        else:
            copies = entries.get(e.entry)
            if not copies:
                continue
            head = copies[0]
            if e.op == DELETE:
                if head.deleted:
                    continue
                if detect and last[e.entry] != e.base:
                    flagged += 1
                for x in copies:
                    x.deleted = True
            elif head.deleted:
                if detect:
                    flagged += 1
            elif e.op == EDIT_AMOUNT:
                if detect and winner[e.entry] != e.base:
                    flagged += 1
                for x in copies:
                    x.amount = e.amount
                winner[e.entry] = e.id
            elif e.op == EDIT_NOTE:
                for x in copies:
                    x.note = e.note
        last[e.entry] = e.id
    return entries, flagged


class ModelServer:
    """In-memory server with switchable safety features. Same interface as ApiBackend."""

    def __init__(self, batch_idem=True, event_dedup=True, order="hlc", conflicts=True, hybrid=True):
        self.batch_idem, self.event_dedup = batch_idem, event_dedup
        self.order, self.conflicts = order, conflicts
        self.rows, self.ids, self.batches, self.seq = {}, {}, {}, 0

    def push(self, merchant, device, batch_id, events):
        if self.batch_idem and batch_id in self.batches:
            return self.batches[batch_id]
        rows = self.rows.setdefault(merchant, [])
        ids = self.ids.setdefault(merchant, set())
        accepted = duplicates = 0
        for e in events:
            if self.event_dedup and e.id in ids:
                duplicates += 1
                continue
            self.seq += 1
            rows.append((self.seq, e))
            ids.add(e.id)
            accepted += 1
        resp = {"batch_id": batch_id, "accepted": accepted, "duplicates": duplicates}
        if self.batch_idem:
            self.batches[batch_id] = resp
        return resp

    def pull(self, merchant, since):
        match = [r for r in self.rows.get(merchant, []) if r[0] > since]
        chunk = match[:500]
        nxt = chunk[-1][0] if chunk else since
        return [e for _, e in chunk], nxt, len(match) > 500

    def state(self, merchant):
        rows = self.rows.get(merchant, [])
        entries, flagged = fold(rows, self.order, self.conflicts, allow_dup=not self.event_dedup)
        flat = [x for lst in entries.values() for x in lst]
        parties = sorted({x.party for x in flat})
        return {
            "events": len(rows),
            "entries_digest": digest_rows([(x.id, x.party, x.amount, x.note, x.deleted) for x in flat]),
            "balances": {p: sum(x.amount for x in flat if x.party == p and not x.deleted) for p in parties},
            "conflicts": flagged,
        }