from core.hlc import Clock, HLC


def test_tick_moves_forward_even_if_wall_clock_goes_back():
    t = [1000]
    c = Clock("A", lambda: t[0])
    first = c.tick()
    t[0] = 900
    assert c.tick() > first


def test_observe_pushes_clock_past_remote():
    c = Clock("A", lambda: 1000)
    remote = HLC(5000, 7, "B")
    c.observe(remote)
    assert c.tick() > remote