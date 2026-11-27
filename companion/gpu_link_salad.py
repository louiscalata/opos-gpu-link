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

On by default when the pinned judge model is in ``runtime/salad/`` next to this file
(sha256 checked once per process; the worker warms it at start) and ``llama-perplexity`` is in ``runtime/``; the env vars
OPOS_GPU_LINK_SALAD_BIN / OPOS_GPU_LINK_SALAD_MODEL still override both.  The judge
runs on the CPU by default (OPOS_GPU_LINK_SALAD_NGL=0), so it never competes with the
answer model for the GPU.
Stdlib only.  Pure function of text + judge; the judge is injectable for tests.
"""
import hashlib, os, re, subprocess, tempfile, threading

REASON = "word_salad"
HEAD_CHARS = 600
TAIL_CHARS = 300
MIN_CHARS = 1000          # shorter answers are never judged
RATIO_THRESHOLD = float(os.environ.get("OPOS_GPU_LINK_SALAD_RATIO", "10"))
MIN_TAIL_PPL = 60.0       # tail must also be absolutely unpredictable
_PPL_RE = re.compile(r"Final estimate: PPL = ([0-9.]+)")
# Pinned judge: bartowski/SmolLM2-135M-Instruct-GGUF, revision 09816acd5d99df7be770d85ea30822623dab342c
# (HuggingFaceTB/SmolLM2-135M-Instruct, Apache-2.0). The sha256 is the Hugging Face LFS oid.
PINNED_MODEL = "SmolLM2-135M-Instruct-Q8_0.gguf"
PINNED_SIZE = 144811360
PINNED_SHA256 = "5a1395716f7913741cc51d98581b9b1228d80987a9f7d3664106742eb06bba83"
RUNTIME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime")


def _ngl():
    """GPU layers for the judge; 0 (CPU) by default so the answer model keeps the GPU."""
    value = os.environ.get("OPOS_GPU_LINK_SALAD_NGL", "0").strip()
    return value if value.isascii() and value.isdigit() else "0"


def _threads():
    """CPU threads for the judge (default 2), so a check never takes every core."""
    value = os.environ.get("OPOS_GPU_LINK_SALAD_THREADS", "2").strip()
    return value if value.isascii() and value.isdigit() and value != "0" else "2"


def _find_binary(runtime_dir):
    """First executable llama-perplexity under runtime_dir, in sorted (stable) order."""
    for root, dirs, files in os.walk(runtime_dir):
        dirs.sort()
        path = os.path.join(root, "llama-perplexity")
        if "llama-perplexity" in files and os.access(path, os.X_OK):
            return path
    return None


def _pinned_model(runtime_dir):
    """The pinned judge model under runtime_dir/salad, only if its size and sha256 match."""
    path = os.path.join(runtime_dir, "salad", PINNED_MODEL)
    try:
        if os.path.getsize(path) != PINNED_SIZE:
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return path if digest.hexdigest() == PINNED_SHA256 else None


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
        # An env var that is set, even to "", is the operator's choice; only unset ones are discovered.
        if binary is None and runtime_dir:
            binary = _find_binary(runtime_dir)
        if not binary:
            return None  # no judge without a binary; skip hashing the model
        if model is None and runtime_dir:
            model = _pinned_model(runtime_dir)
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
            p = subprocess.run([self.binary, "-m", self.model, "-f", path, "-c", "16", "-ngl", _ngl(), "-t", _threads()],
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
_DEFAULT_LOCK = threading.Lock()


def default_judge():
    """Judge from OPOS_GPU_LINK_SALAD_BIN/MODEL, else the pinned model and llama-perplexity
    under runtime/ (None when neither is there)."""
    with _DEFAULT_LOCK:  # one discovery and one model hash per process
        if "j" not in _DEFAULT:
            _DEFAULT["j"] = PerplexityJudge.from_env(RUNTIME_DIR) if enabled() else None
        return _DEFAULT["j"]


def warm():
    """Resolve the default judge in the background (the model hash takes about 0.3 s)."""
    threading.Thread(target=default_judge, name="salad-warm", daemon=True).start()


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
