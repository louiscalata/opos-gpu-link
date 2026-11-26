"""Conservative, bounded text heuristics; these cannot establish factual accuracy.

The streaming state quarantines a small suffix so a detected loop is never
committed to an append-only consumer. There are no model or network dependencies.
"""
from __future__ import annotations

import re
import unicodedata


DEFAULT_MAX_CHARS = 8192
TAIL_WINDOW_CHARS = 1024
QUARANTINE_CHARS = 512
CHECK_CHARS = 32
REPEAT_CHAR_COUNT = 40
LOOP_REPEATS = 6
MIN_LOOP_CHARS = 48
MAX_FRAGMENT_CHARS = 64
MAX_NGRAM_TOKENS = 8
MAX_LOOP_SPAN = MAX_FRAGMENT_CHARS * LOOP_REPEATS
NON_TEXT_CHARS = 64
NON_TEXT_RATIO = 0.8
REPLACEMENT_COUNT = 3

# Markdown decoration and ordinary whitespace are intentionally exempt.
_RUN = re.compile(r"([^\s\-=*_#~.`|])\1{" + str(REPEAT_CHAR_COUNT - 1) + r",}")
_FRAGMENT = re.compile(r"([^\r\n]{4," + str(MAX_FRAGMENT_CHARS) + r"}?)\1{" + str(LOOP_REPEATS - 1) + r",}")
_WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
_ENCODING = re.compile(
    r"\x00|\ufffd{" + str(REPLACEMENT_COUNT) + r",}|<\|[^\r\n<>]{1,64}\|>|<unused\d+>"
    r"|Ã[\x80-\xbf]|Â[\x80-\xbf]|â€[™œž“”‘’¦—–]?|ðŸ"
)
_DECORATION = frozenset("-=*_#~.`|:+ \t\r\n")


def _finding(tail: str, final: bool) -> tuple[str, int] | None:
    """Return the most specific reason and its suspicious offset in a window."""
    findings: list[tuple[int, int, str]] = []
    for match in _ENCODING.finditer(tail):
        findings.append((match.start(), 0, "encoding_junk"))
    for match in _RUN.finditer(tail):
        findings.append((match.start(), 1, "repeat_char"))
    for match in _FRAGMENT.finditer(tail):
        if len(match.group()) >= MIN_LOOP_CHARS and any(ch.isalnum() for ch in match.group(1)):
            findings.append((match.start(), 2, "ngram_loop"))

    # Normalizing whitespace catches token loops even when token separators vary.
    words = list(_WORD.finditer(tail))
    values = [match.group().casefold() for match in words]
    for start in range(len(words)):
        for width in range(1, MAX_NGRAM_TOKENS + 1):
            end = start + width * LOOP_REPEATS
            if end > len(words):
                break
            begin_char, end_char = words[start].start(), words[end - 1].end()
            span = end_char - begin_char
            if span < MIN_LOOP_CHARS or span > MAX_LOOP_SPAN:
                continue
            phrase = values[start:start + width]
            if values[start:end] == phrase * LOOP_REPEATS:
                findings.append((begin_char, 2, "ngram_loop"))
                break

    # Only a wordless suffix is judged by symbol density. Letters from all
    # scripts and digits protect ordinary prose, code, lists and mathematics.
    start = len(tail)
    while start and not tail[start - 1].isalnum() and tail[start - 1] != "_":
        start -= 1
    suffix = tail[start:]
    significant = [ch for ch in suffix if not ch.isspace()]
    if len(significant) >= NON_TEXT_CHARS and not all(ch in _DECORATION for ch in significant):
        noisy = sum(unicodedata.category(ch)[0] in "CS" or ch in "@$%&!?" for ch in significant)
        if noisy / len(significant) >= NON_TEXT_RATIO:
            # Retain the preceding sentence's punctuation and whitespace.
            first_noise = next(index for index, ch in enumerate(suffix)
                               if not ch.isspace() and ch not in _DECORATION)
            findings.append((start + first_noise, 3, "non_text"))
    # A sufficiently long control run is invalid before the response finishes.
    control_start, control_count = 0, 0
    for index, ch in enumerate(tail):
        if unicodedata.category(ch) == "Cc" and ch not in "\t\r\n":
            if not control_count:
                control_start = index
            control_count += 1
            if control_count >= NON_TEXT_CHARS:
                findings.append((control_start, 3, "non_text"))
                break
        else:
            control_count = 0
    if not findings:
        return None
    _, _, reason = min(findings, key=lambda finding: (finding[1], finding[0]))
    # A more specific later fault must not release an earlier bad span. For
    # example, a NUL can arrive in the same check slice as the 40th repeated @.
    return reason, min(finding[0] for finding in findings)


def garble_reason(text: str, final: bool = False, max_chars: int = DEFAULT_MAX_CHARS) -> str | None:
    """Classify a bounded tail, or a total length over the configured answer cap.

    This is suitable for repeated calls with a cumulative answer. To inspect
    every byte of unusually large chunks, use GuardState instead.
    """
    if max_chars < 0:
        raise ValueError("max_chars must be nonnegative")
    finding = _finding(text[-TAIL_WINDOW_CHARS:], final)
    if finding is not None:
        return finding[0]
    return "runaway_length" if len(text) > max_chars else None


class GuardState:
    """Consume new raw text and expose only a monotonic, safe prefix.

    ``initial_text`` is already acknowledged text and is never trimmed or
    reclassified. ``detected_at`` records the first checked character position
    that failed (at most CHECK_CHARS after sufficient bad evidence arrived).
    A clean final flush releases the quarantine; later input is ignored.
    """

    def __init__(self, initial_text: str = "", max_chars: int = DEFAULT_MAX_CHARS, salad=None):
        """``salad`` is an optional object with update(text)->reason and final(text)->reason
        (gpu_link_salad.BackgroundSalad). It is advisory: any error in it is ignored."""
        self._salad = salad
        if max_chars < 0:
            raise ValueError("max_chars must be nonnegative")
        self.max_chars = max_chars
        self.safe_text = initial_text
        self.reason: str | None = None
        self.detected_at: int | None = None
        self._pending = ""
        self._received = len(initial_text)
        self._final = False

    @property
    def text(self) -> str:
        """Current prefix plus quarantined text, excluding any discarded suffix."""
        return self.safe_text + self._pending

    def feed(self, piece: str, final: bool = False) -> str | None:
        if self.reason is not None or self._final:
            return self.reason
        for offset in range(0, len(piece), CHECK_CHARS):
            chunk = piece[offset:offset + CHECK_CHARS]
            self._pending += chunk
            self._received += len(chunk)
            finding = _finding(self._pending, False)
            if finding is not None:
                self.reason, start = finding
                self.safe_text += self._pending[:start]
                self._pending = ""
                self.detected_at = self._received
                return self.reason
            if self._received > self.max_chars:
                self.reason = "runaway_length"
                overflow = self._received - self.max_chars
                self.safe_text += self._pending[:max(0, len(self._pending) - overflow)]
                self._pending = ""
                self.detected_at = self._received
                return self.reason
            if self._salad is not None and self._salad_hit():
                return self.reason
            ready = len(self._pending) - QUARANTINE_CHARS
            if ready > 0:
                self.safe_text += self._pending[:ready]
                self._pending = self._pending[ready:]
        if final:
            finding = _finding(self._pending, True)
            if finding is not None:
                self.reason, start = finding
                self.safe_text += self._pending[:start]
                self.detected_at = self._received
            elif self._salad is not None and self._salad_hit(final=True):
                return self.reason
            else:
                self.safe_text += self._pending
            self._pending = ""
            self._final = True
        return self.reason

    def _salad_hit(self, final: bool = False) -> bool:
        """Word-salad verdict from the optional judge; the quarantined suffix is dropped."""
        try:
            text = self.text
            reason = self._salad.final(text) if final else self._salad.update(text)
        except Exception:  # advisory only
            return False
        if not reason:
            return False
        self.reason = reason
        self._pending = ""
        self.detected_at = self._received
        if final:
            self._final = True
        return True
