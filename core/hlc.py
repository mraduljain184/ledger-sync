import time
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class HLC:
    wall: int      # milliseconds
    counter: int
    device: str


class Clock:
    def __init__(self, device, now_fn=None, hybrid=True):
        self.device = device
        self._now = now_fn or (lambda: int(time.time() * 1000))
        self.hybrid = hybrid      # False = plain wall clock, used for the baselines
        self.wall = 0
        self.counter = 0

    def tick(self):
        """Timestamp for a local event."""
        pt = self._now()
        if not self.hybrid:
            return HLC(pt, 0, self.device)
        if pt > self.wall:
            self.wall, self.counter = pt, 0
        else:
            self.counter += 1
        return HLC(self.wall, self.counter, self.device)

    def observe(self, remote):
        """Call when an event from another device arrives."""
        if not self.hybrid:
            return
        pt = self._now()
        new_wall = max(self.wall, remote.wall, pt)
        if new_wall == self.wall == remote.wall:
            self.counter = max(self.counter, remote.counter) + 1
        elif new_wall == self.wall:
            self.counter += 1
        elif new_wall == remote.wall:
            self.counter = remote.counter + 1
        else:
            self.counter = 0
        self.wall = new_wall