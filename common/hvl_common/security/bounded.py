"""
Size-bounded in-process containers for small hot caches (key material, Fernet rings, per-path init flags).
"""

from __future__ import annotations

from collections import OrderedDict


class BoundedDict(OrderedDict):
    """An OrderedDict that drops its oldest-written entry once it holds more than `maxsize`."""

    def __init__(self, *args, maxsize: int = 512, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > self.maxsize:
            self.popitem(last=False)

    def copy(self):
        return type(self)(self, maxsize=self.maxsize)


class BoundedSet(set):
    """A set that drops an arbitrary member once it holds more than `maxsize`."""

    def __init__(self, *args, maxsize: int = 512, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def add(self, item):
        super().add(item)
        if len(self) > self.maxsize:
            self.pop()

    def copy(self):
        return type(self)(self, maxsize=self.maxsize)
