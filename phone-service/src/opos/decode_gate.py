# SPDX-License-Identifier: Apache-2.0
"""Shared decode gate and Stop-cancel flag order.

The lead phone lane and the extra phone-pool lanes share one decoder. Pool lanes
wait until the phone lead is done. Stop must set every targeted lane's cancel
flag before any teardown that can release this gate; otherwise a queued pool
lane can start after the lead is cancelled (the T4a race).
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable
from typing import Any


class DecodeGate:
    """Give pool models FIFO turns and keep the phone decoder out of each turn."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.queue: deque[object] = deque()
        self.active: object | None = None
        self.phone_pending = 0

    def reserve_phone(self) -> None:
        with self.condition:
            self.phone_pending += 1
            self.condition.notify_all()

    def phone_turn(self, cancelled: threading.Event) -> bool:
        with self.condition:
            while self.active is not None:
                if cancelled.is_set():
                    return False
                self.condition.wait(0.05)
            return not cancelled.is_set()

    def release_phone(self) -> None:
        with self.condition:
            if self.phone_pending > 0:
                self.phone_pending -= 1
            self.condition.notify_all()

    def reserve_pool(self) -> object:
        with self.condition:
            ticket = object()
            self.queue.append(ticket)
            self.condition.notify_all()
            return ticket

    def pool_turn(self, ticket: object, cancelled: threading.Event) -> bool:
        with self.condition:
            while True:
                if cancelled.is_set():
                    self._release_pool_locked(ticket)
                    return False
                if self.active is None and self.phone_pending == 0 and self.queue and self.queue[0] is ticket:
                    self.queue.popleft()
                    self.active = ticket
                    if cancelled.is_set():
                        self._release_pool_locked(ticket)
                        return False
                    return True
                self.condition.wait(0.05)

    def release_pool(self, ticket: object) -> None:
        with self.condition:
            self._release_pool_locked(ticket)

    def _release_pool_locked(self, ticket: object) -> None:
        if self.active is ticket:
            self.active = None
        else:
            try:
                self.queue.remove(ticket)
            except ValueError:
                pass
        self.condition.notify_all()


def set_cancel_flags(jobs: Iterable[Any], gate: DecodeGate | None = None) -> None:
    """Set every worker's cancel flag before any teardown that may release the gate.

    When a gate is given, all flags are set under that gate's lock so a lead
    lane cannot release the decoder before a queued pool lane is flagged.
    """
    events = [job.cancelled for job in jobs if job is not None]
    if gate is None:
        for event in events:
            event.set()
        return
    with gate.condition:
        for event in events:
            event.set()
        gate.condition.notify_all()
