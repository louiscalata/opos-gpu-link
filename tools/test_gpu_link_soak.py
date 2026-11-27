# SPDX-License-Identifier: Apache-2.0
"""Fast, device-free checks for the paced GPU Link simulator."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import socket
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("gpu_link_soak", Path(__file__).with_name("gpu-link-soak.py"))
assert SPEC is not None and SPEC.loader is not None
soak = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(soak)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


class SoakTests(unittest.TestCase):
    def test_defaults_have_a_longer_cooldown(self) -> None:
        args = soak.arguments([])
        self.assertGreater(args.gap, 0)
        self.assertGreater(args.cooldown, args.gap)
        self.assertGreater(args.duration, args.cooldown)
        self.assertGreater(args.cooldown_every, 0)

    def test_invalid_schedule_is_rejected(self) -> None:
        for argv in (["--gap", "0"], ["--duration", "nan"],
                     ["--cooldown-every", "0"], ["--gap", "5", "--cooldown", "4"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    soak.arguments(argv)

    def test_four_lane_shape_and_pacing(self) -> None:
        service = soak.SimulatedPhoneService()
        clock = FakeClock()
        events: list[str] = []
        stats = soak.run_soak(duration=11, gap=2, cooldown=5, cooldown_every=2,
                              service=service, clock=clock.clock, sleep=clock.sleep,
                              emit=events.append)
        self.assertEqual(clock.waits, [2, 5, 2, 2])
        self.assertEqual(stats, {"questions": 4, "full_cooldowns": 1, "elapsed_seconds": 11})
        self.assertEqual(len(service.requests), 4)
        self.assertTrue(all(request["action"] == "ask"
                            and request["panes"] == ["gpu", "g1", "g2", "g3"]
                            for request in service.requests))
        self.assertEqual(events, [f"Question {n}: 4/4 simulated Done" for n in range(1, 5)])

    def test_no_socket_port_or_device_process_access(self) -> None:
        # No socket means no bind or connection to any reserved demo port.
        forbidden = AssertionError("simulator must not access sockets or device commands")
        output = io.StringIO()
        with (patch.object(socket, "socket", side_effect=forbidden),
              patch.object(subprocess, "Popen", side_effect=forbidden),
              patch.object(subprocess, "run", side_effect=forbidden),
              patch.object(os, "system", side_effect=forbidden),
              contextlib.redirect_stdout(output)):
            self.assertEqual(soak.main(["--duration", "0.012", "--gap", "0.003",
                                        "--cooldown", "0.006", "--cooldown-every", "2"]), 0)
        self.assertIn("Completed", output.getvalue())


if __name__ == "__main__":
    unittest.main()
