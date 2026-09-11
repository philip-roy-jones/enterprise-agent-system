"""Cooperative action deadlines; never abandon a still-running desktop thread."""

import time
from enterprise.shared.types import Recovery


class OperationTimeout(Recovery):
    def __init__(self):
        super().__init__("temporary", "Operation deadline expired; observe before retrying")


class Deadline:
    def __init__(self, seconds):
        self.expires = time.monotonic() + seconds

    def remaining(self, maximum=None):
        remaining = self.expires - time.monotonic()
        if remaining <= 0:
            raise OperationTimeout()
        return remaining if maximum is None else min(remaining, maximum)

    def check(self):
        self.remaining()
