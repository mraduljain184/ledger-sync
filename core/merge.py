import hashlib
import json
from dataclasses import dataclass, field
from core.events import CREATE, EDIT_AMOUNT, EDIT_NOTE, DELETE


@dataclass
class Entry:
    id: str
    party: str
    amount: int
    note: str
    deleted: bool = False


@dataclass(frozen=True)
class Conflict:
    entry: str
    kind: str      # "amount" or "delete_vs_edit"
    earlier: str   # event id
    later: str     # event id


@dataclass
class State:
    entries: dict
    conflicts: list
    amount_winner: dict = field(default_factory=dict)
    last: dict = field(default_factory=dict)


def build_state(events):
    unique = {e.id: e for e in events}      # duplicates vanish here
    entries, conflicts = {}, []
    amount_winner = {}                      # entry -> id of current amount event
    last = {}                               # entry -> id of latest event seen so far

    for e in sorted(unique.values(), key=lambda x: (x.hlc, x.id)):
        if e.op == CREATE:
            if e.entry in entries:
                continue
            entries[e.entry] = Entry(e.entry, e.party, e.amount, e.note)
            amount_winner[e.entry] = e.id
        else:
            entry = entries.get(e.entry)
            if entry is None:
                continue
            if e.op == DELETE:
                if entry.deleted:
                    continue
                if last[e.entry] != e.base:
                    conflicts.append(Conflict(e.entry, "delete_vs_edit", last[e.entry], e.id))
                entry.deleted = True
            elif entry.deleted:
                conflicts.append(Conflict(e.entry, "delete_vs_edit", last[e.entry], e.id))
            elif e.op == EDIT_AMOUNT:
                if amount_winner[e.entry] != e.base:
                    conflicts.append(Conflict(e.entry, "amount", amount_winner[e.entry], e.id))
                entry.amount = e.amount
                amount_winner[e.entry] = e.id
            elif e.op == EDIT_NOTE:
                entry.note = e.note
        last[e.entry] = e.id

    return State(entries, conflicts, amount_winner, last)


def balance(state, party):
    return sum(x.amount for x in state.entries.values()
               if x.party == party and not x.deleted)


def digest(state):
    rows = [(x.id, x.party, x.amount, x.note, x.deleted)
            for x in sorted(state.entries.values(), key=lambda x: x.id)]
    cons = sorted((c.entry, c.kind, c.earlier, c.later) for c in state.conflicts)
    return hashlib.sha256(json.dumps([rows, cons]).encode()).hexdigest()