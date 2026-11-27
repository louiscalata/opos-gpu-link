# SPDX-License-Identifier: Apache-2.0
"""Paced, simulated GPU Link four-lane soak; no device or companion access.

On 26 Nov 2026, a live Flip 30-minute soak stopped at 17/30 minutes when
Thermal Status reached 4 and SKIN reached 47.1 C. Two four-lane rounds were
Done with no failures or restarts and flat memory. That is not a completed
30-minute soak. A later live run should start with a cool phone and include
cool-down gaps; this tool only exercises the pacing with an in-process stand-in.
"""

from __future__ import annotations

import argparse
import math
import time
from collections.abc import Callable
from typing import Any


PANES = ("gpu", "g1", "g2", "g3")  # phone-service/src/opos/ai_answers.py


class SimulatedPhoneService:
    """Stand in for the phone service's POST /api/ai ask and snapshot shape."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def post(self, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if (data.get("action") != "ask" or data.get("panes") != list(PANES)
                or not isinstance(data.get("question"), str) or not data["question"].strip()):
            return 400, {"error": "invalid simulated ask"}
        self.requests.append(data.copy())
        answer = lambda pane: {"pane": pane, "question": data["question"], "state": "done"}
        return 200, {
            "gpu": {"answer": answer("gpu")},
            "models": [{"pane": pane, "answer": answer(pane)} for pane in PANES[1:]],
        }


def _all_done(snapshot: dict[str, Any]) -> bool:
    answers = {"gpu": snapshot.get("gpu", {}).get("answer")}
    answers.update({item.get("pane"): item.get("answer") for item in snapshot.get("models", [])})
    return all(isinstance(answers.get(pane), dict)
               and answers[pane].get("state") == "done" for pane in PANES)


def validate_schedule(duration: float, gap: float, cooldown: float, cooldown_every: int) -> None:
    if any(not math.isfinite(value) or value <= 0 for value in (duration, gap, cooldown)):
        raise ValueError("duration, gap and cooldown must be finite positive seconds")
    if cooldown < gap:
        raise ValueError("cooldown must be at least as long as gap")
    if cooldown_every < 1:
        raise ValueError("cooldown-every must be a positive question count")


def run_soak(*, duration: float, gap: float, cooldown: float, cooldown_every: int,
             service: SimulatedPhoneService, clock: Callable[[], float] = time.monotonic,
             sleep: Callable[[float], None] = time.sleep,
             emit: Callable[[str], None] = print) -> dict[str, float | int]:
    """Ask four fake lanes, then wait after each answer until the duration ends."""
    validate_schedule(duration, gap, cooldown, cooldown_every)
    started = clock()
    deadline = started + duration
    questions = 0
    full_cooldowns = 0
    while clock() < deadline:
        question = f"Simulated GPU Link check {questions + 1}."
        status, snapshot = service.post({"action": "ask", "question": question, "panes": list(PANES)})
        if status != 200 or not _all_done(snapshot):
            raise RuntimeError(f"simulated four-lane ask failed at question {questions + 1}")
        questions += 1
        emit(f"Question {questions}: 4/4 simulated Done")

        cooling = questions % cooldown_every == 0
        pause = cooldown if cooling else gap
        remaining = deadline - clock()
        if remaining <= 0:
            break
        waited = min(pause, remaining)
        sleep(waited)
        if cooling and waited == pause:
            full_cooldowns += 1
    return {"questions": questions, "full_cooldowns": full_cooldowns,
            "elapsed_seconds": clock() - started}


def _positive_seconds(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use a number of seconds") from exc
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("use finite positive seconds")
    return value


def _positive_count(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use a positive question count") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("use a positive question count")
    return value


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--duration", type=_positive_seconds, default=300.0,
                        help="total simulated run time in seconds (default: 300)")
    parser.add_argument("--gap", type=_positive_seconds, default=30.0,
                        help="seconds after each question (default: 30)")
    parser.add_argument("--cooldown", type=_positive_seconds, default=120.0,
                        help="longer pause in seconds (default: 120)")
    parser.add_argument("--cooldown-every", type=_positive_count, default=2,
                        help="take a cooldown after this many questions (default: 2)")
    args = parser.parse_args(argv)
    if args.cooldown < args.gap:
        parser.error("--cooldown must be at least --gap")
    return args


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    print("Simulated phone-service /api/ai: four fake lanes; no device connection.")
    stats = run_soak(duration=args.duration, gap=args.gap, cooldown=args.cooldown,
                     cooldown_every=args.cooldown_every, service=SimulatedPhoneService())
    print(f"Completed {stats['questions']} simulated questions with "
          f"{stats['full_cooldowns']} full cool-down gaps in {stats['elapsed_seconds']:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
