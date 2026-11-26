"""Optional word-salad detector for GPU Link answers (companion / validator only).

The cheap guards in gpu_link_guard catch repeated characters, n-gram loops and
encoding junk.  They cannot see *fluent-looking nonsense* (shuffled or
unrelated words).  This module scores the answer with a tiny local LM
(SmolLM2-135M through the pinned llama-perplexity) and flags answers whose
tail is far less predictable than their own opening:

    ratio = PPL(last TAIL_CHARS) / PPL(first HEAD_CHARS)

Using the answer's own opening as the baseline cancels topic/style difficulty.
Reason code: ``word_salad``.  Disabled with OPOS_GPU_LINK_SALAD=0, and silently
inactive (never an error, never a false alarm) when the binary/model are absent.
Stdlib only.  Pure function of text + judge; the judge is injectable for tests.
"""
import os, re, subprocess, tempfile, threading

REASON = "word_salad"
HEAD_CHARS = 600
TAIL_CHARS = 300
MIN_CHARS = 1000          # shorter answers are never judged
RATIO_THRESHOLD = float(os.environ.get("OPOS_GPU_LINK_SALAD_RATIO", "10"))
MIN_TAIL_PPL = 60.0       # tail must also be absolutely unpredictable
_PPL_RE = re.compile(r"Final estimate: PPL = ([0-9.]+)")


def enabled():
    return os.environ.get("OPOS_GPU_LINK_SALAD", "1") not in ("0", "off", "false", "no")


class PerplexityJudge:
    """Runs `llama-perplexity -c 16` on a text; returns PPL or None."""

    def __init__(self, binary, model, timeout=30.0, workdir=None):
        self.binary, self.model, self.timeout, self.workdir = binary, model, timeout, workdir

    @classmethod
    def from_env(cls, runtime_dir=None):
        binary = os.environ.get("OPOS_GPU_LINK_SALAD_BIN")
        model = os.environ.get("OPOS_GPU_LINK_SALAD_MODEL")
        if not binary and runtime_dir:
            for root, _d, files in os.walk(runtime_dir):
                if "llama-perplexity" in files:
                    binary = os.path.join(root, "llama-perplexity"); break
        if binary and model and os.path.isfile(binary) and os.path.isfile(model):
            return cls(binary, model)
        return None

    def ppl(self, text):
        text = text.strip()
        if len(text) < 40:
            return None
        fd, path = tempfile.mkstemp(suffix=".txt", dir=self.workdir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            p = subprocess.run([self.binary, "-m", self.model, "-f", path, "-c", "16", "-ngl", "99"],
                               capture_output=True, text=True, timeout=self.timeout)
            m = _PPL_RE.search(p.stdout + p.stderr)
            return float(m.group(1)) if m else None
        except (OSError, subprocess.SubprocessError):
            return None
        finally:
            try: os.unlink(path)
            except OSError: pass


def _clip(text):
    t = text.strip()
    head = t[:HEAD_CHARS]
    tail = t[-TAIL_CHARS:]
    # drop a cut-off first/last word so truncation itself is not "surprising"
    if " " in tail: tail = tail.split(" ", 1)[1]
    return head, tail


def score(text, judge):
    """Returns (ratio, head_ppl, tail_ppl) or None when it cannot be judged."""
    t = (text or "").strip()
    if judge is None or len(t) < MIN_CHARS:
        return None
    head, tail = _clip(t)
    hp, tp = judge.ppl(head), judge.ppl(tail)
    if not hp or not tp:
        return None
    return tp / hp, hp, tp


def salad_reason(text, judge):
    """'word_salad' or None."""
    if not enabled():
        return None
    s = score(text, judge)
    if s and s[0] >= RATIO_THRESHOLD and s[2] >= MIN_TAIL_PPL:
        return REASON
    return None


_DEFAULT = {}


def default_judge():
    """Judge configured by OPOS_GPU_LINK_SALAD_BIN/MODEL (None when unconfigured)."""
    if "j" not in _DEFAULT:
        _DEFAULT["j"] = PerplexityJudge.from_env() if enabled() else None
    return _DEFAULT["j"]


def set_default_judge(judge):
    _DEFAULT["j"] = judge


class BackgroundSalad:
    """Non-blocking wrapper for streaming: call update(full_text) as text grows;
    poll .reason.  Judges at most every STEP chars, one job at a time."""
    STEP = 300

    def __init__(self, judge):
        self.judge, self.reason, self._last, self._busy = judge, None, 0, False
        self._lock = threading.Lock()

    def update(self, text):
        if self.reason or self.judge is None or not enabled() or len(text) < MIN_CHARS:
            return self.reason
        with self._lock:
            if self._busy or len(text) - self._last < self.STEP:
                return self.reason
            self._busy, self._last = True, len(text)
        threading.Thread(target=self._run, args=(text,), daemon=True).start()
        return self.reason

    def final(self, text):
        """Synchronous end-of-answer check; also honours an earlier streaming hit."""
        if self.reason is None and self.judge is not None:
            self.reason = salad_reason(text, self.judge)
        return self.reason

    def _run(self, text):
        try:
            r = salad_reason(text, self.judge)
            if r: self.reason = r
        finally:
            self._busy = False
