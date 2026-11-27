# SPDX-License-Identifier: Apache-2.0
"""T4a Stop race: cancelling the phone lead must not start a queued pool lane."""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace

from opos.decode_gate import DecodeGate, set_cancel_flags


class _FlagAfterAcquire(threading.Event):
    """Looks cancelled only once this ticket has become the active holder."""

    def __init__(self, gate: DecodeGate, ticket: object) -> None:
        super().__init__()
        self._gate = gate
        self._ticket = ticket

    def is_set(self) -> bool:
        if self._gate.active is self._ticket:
            return True
        return super().is_set()


class DecodeGateStop(unittest.TestCase):
    def _wait_until(self, pred, timeout=2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return True
            time.sleep(0.01)
        return False

    def _start_waiting_pool(self, gate, ticket, pool_flag, result):
        entered = threading.Event()
        original = gate.pool_turn

        def wrapped(ticket_arg, cancelled):
            entered.set()
            return original(ticket_arg, cancelled)

        gate.pool_turn = wrapped  # type: ignore[method-assign]

        def waiter():
            result.append("started" if gate.pool_turn(ticket, pool_flag) else "cancelled")

        thread = threading.Thread(target=waiter)
        thread.start()
        self.assertTrue(self._wait_until(entered.is_set))
        # One wait interval so the waiter is inside condition.wait, not just entered.
        self.assertTrue(self._wait_until(lambda: thread.is_alive() and not result))
        time.sleep(0.08)
        return thread

    def test_t4a_order_without_flagging_the_pool_first_lets_it_start(self):
        """Pre-fix Stop order: the phone lead releases the shared gate while
        the queued pool lane's cancel flag is still clear, so the pool lane
        starts. This pins the T4a race.
        """
        gate = DecodeGate()
        pool_flag = threading.Event()
        ticket = gate.reserve_pool()
        gate.reserve_phone()
        result = []
        thread = self._start_waiting_pool(gate, ticket, pool_flag, result)
        gate.release_phone()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["started"])
        gate.release_pool(ticket)

    def test_t4a_stop_sets_every_flag_before_the_gate_is_released(self):
        """Fixed Stop order: every targeted cancel flag is set under the gate
        lock, then the phone lead may release. The queued pool lane must not
        start, even if a phone-lead thread releases as soon as it is flagged.
        """
        gate = DecodeGate()
        phone_flag = threading.Event()
        pool_flag = threading.Event()
        ticket = gate.reserve_pool()
        gate.reserve_phone()
        result = []
        thread = self._start_waiting_pool(gate, ticket, pool_flag, result)

        lead_ready = threading.Event()

        def phone_lead():
            lead_ready.set()
            phone_flag.wait(2)
            gate.release_phone()

        lead = threading.Thread(target=phone_lead)
        lead.start()
        self.assertTrue(self._wait_until(lead_ready.is_set))
        set_cancel_flags(
            (
                SimpleNamespace(cancelled=phone_flag),
                SimpleNamespace(cancelled=pool_flag),
            ),
            gate=gate,
        )
        self.assertTrue(phone_flag.is_set())
        self.assertTrue(pool_flag.is_set())
        lead.join(2)
        thread.join(2)
        self.assertFalse(lead.is_alive())
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, ["cancelled"])
        self.assertIsNone(gate.active)
        self.assertEqual(len(gate.queue), 0)

    def test_pool_turn_drops_the_gate_if_cancelled_after_acquire(self):
        """If the flag becomes set in the window after the lane is made
        active, pool_turn must give the gate back and not start.
        """
        gate = DecodeGate()
        ticket = gate.reserve_pool()
        flag = _FlagAfterAcquire(gate, ticket)
        started = gate.pool_turn(ticket, flag)
        self.assertFalse(started)
        self.assertIsNone(gate.active)
        self.assertEqual(len(gate.queue), 0)
