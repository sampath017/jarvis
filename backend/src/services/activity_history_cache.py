"""Bounded, versioned history reuse; never substitute a truncated window."""
from collections import OrderedDict
from copy import deepcopy
import json
import threading
import time


class ActivityHistoryCache:
    def __init__(self, max_entries=12, max_bytes=8 * 1024 * 1024, ttl=120):
        self.entries = OrderedDict()
        self.max_entries, self.max_bytes, self.ttl = max_entries, max_bytes, ttl
        self.lock = threading.RLock()

    def get_or_compute(self, key, version, compute):
        revision = version()
        if revision is None:
            return compute()
        # Coalesce repeated work on this instance, with a strict memory bound.
        with self.lock:
            now = time.monotonic()
            saved = self.entries.get(key)
            if saved and saved[0] == revision and now - saved[1] < self.ttl:
                self.entries.move_to_end(key)
                return deepcopy(saved[2])
            result = compute()
            if result.get('truncated') or result.get('prelude_truncated'):
                return result
            # An observation arriving during the computation prevents reuse.
            if version() != revision:
                return result
            size = len(json.dumps(result, default=str).encode())
            if size <= self.max_bytes:
                self.entries[key] = (revision, now, deepcopy(result), size)
                self.entries.move_to_end(key)
                while len(self.entries) > self.max_entries or sum(row[3] for row in self.entries.values()) > self.max_bytes:
                    self.entries.popitem(last=False)
            return result


history_cache = ActivityHistoryCache()
