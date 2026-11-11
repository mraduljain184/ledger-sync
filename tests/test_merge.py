import random
from hypothesis import given, strategies as st

from core.events import Event, CREATE, EDIT_AMOUNT, EDIT_NOTE, DELETE
from core.hlc import HLC
from core.merge import build_state, balance, digest


def test_two_phones_edit_same_amount_offline():
    create = Event("c1", "A", HLC(90, 0, "A"), "e1", CREATE, party="ramesh", amount=50000)
    a = Event("a1", "A", HLC(100, 0, "A"), "e1", EDIT_AMOUNT, amount=45000, base="c1")
    b = Event("b1", "B", HLC(103, 0, "B"), "e1", EDIT_AMOUNT, amount=48000, base="c1")

    s = build_state([create, a, b])
    assert s.entries["e1"].amount == 48000       # greater HLC wins
    assert len(s.conflicts) == 1                 # but it is flagged

    fix = Event("r1", "A", HLC(110, 0, "A"), "e1", EDIT_AMOUNT, amount=45000, base="b1")
    s2 = build_state([create, a, b, fix])
    assert s2.entries["e1"].amount == 45000
    assert balance(s2, "ramesh") == 45000


def test_delete_wins_over_unseen_edit():
    create = Event("c1", "A", HLC(10, 0, "A"), "e1", CREATE, party="sita", amount=100)
    edit = Event("x1", "B", HLC(20, 0, "B"), "e1", EDIT_AMOUNT, amount=200, base="c1")
    delete = Event("d1", "A", HLC(25, 0, "A"), "e1", DELETE, base="c1")
    s = build_state([create, edit, delete])
    assert s.entries["e1"].deleted
    assert balance(s, "sita") == 0
    assert [c.kind for c in s.conflicts] == ["delete_vs_edit"]


@st.composite
def event_lists(draw):
    n = draw(st.integers(1, 25))
    ids = [f"e{i}" for i in range(n)]
    out = []
    for i in range(n):
        dev = draw(st.sampled_from(["A", "B", "C"]))
        out.append(Event(
            id=ids[i], device=dev,
            hlc=HLC(draw(st.integers(1, 50)), draw(st.integers(0, 3)), dev),
            entry=draw(st.sampled_from(["x", "y"])),
            op=draw(st.sampled_from([CREATE, EDIT_AMOUNT, EDIT_NOTE, DELETE])),
            party=draw(st.sampled_from(["ram", "sita"])),
            amount=draw(st.integers(-1000, 1000)),
            note=draw(st.text(max_size=3)),
            base=draw(st.sampled_from([None] + ids)),
        ))
    return out


@given(event_lists(), st.randoms())
def test_order_does_not_matter(events, rnd):
    shuffled = list(events)
    rnd.shuffle(shuffled)
    assert digest(build_state(events)) == digest(build_state(shuffled))


@given(event_lists())
def test_duplicates_do_not_matter(events):
    assert digest(build_state(events)) == digest(build_state(events + events))


@given(event_lists(), st.integers(0, 24), st.integers(0, 24))
def test_merge_grouping_does_not_matter(events, i, j):
    i, j = sorted((i % (len(events) + 1), j % (len(events) + 1)))
    a, b, c = events[:i], events[i:j], events[j:]
    left = build_state((a + b) + c)
    right = build_state(a + (b + c))
    assert digest(left) == digest(right)