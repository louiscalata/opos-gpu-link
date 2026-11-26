# SPDX-License-Identifier: Apache-2.0
"""Bounded demo defaults for launcher-owned llama-server instances.

These are conservative starting points, not measured quality guarantees.
Chat templates and end-of-generation tokens stay with the GGUF metadata.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class GenerationProfile:
    family: str
    temp: float = 0.4
    top_p: float = 0.9
    top_k: int = 40
    min_p: float = 0.05
    repeat_penalty: float = 1.1
    repeat_last_n: int = 128
    dry_multiplier: float = 0.6
    dry_base: float = 1.75
    dry_allowed_length: int = 4
    dry_penalty_last_n: int = 128
    n_predict: int = 384


# Intentionally modest demo presets, rather than vendor benchmark settings.
GENERATION_PROFILES = {
    "generic": GenerationProfile("generic"),
    "gemma3": GenerationProfile("gemma3", temp=0.5),
    "gemma4": GenerationProfile("gemma4", temp=0.5),
    "llama3": GenerationProfile("llama3", temp=0.5),
    "qwen25": GenerationProfile("qwen25", temp=0.4),
    "qwen3": GenerationProfile("qwen3", temp=0.6, top_p=0.95, top_k=20,
                               min_p=0.0, n_predict=512),
    "phi": GenerationProfile("phi", temp=0.4),
    "mistral": GenerationProfile("mistral", temp=0.5),
    "lfm": GenerationProfile("lfm", temp=0.3),
    "smollm": GenerationProfile("smollm", temp=0.4),
    "granite": GenerationProfile("granite", temp=0.4),
    "deepseek": GenerationProfile("deepseek", temp=0.5, n_predict=512),
    "glm": GenerationProfile("glm", temp=0.5, n_predict=512),
}

# Use only the file name, never a parent directory or an incidental substring.
# Unknown versions keep the generic preset and their own embedded template.
_FAMILIES = tuple((family, re.compile(pattern, re.I)) for family, pattern in (
    ("gemma3", r"(?:^|[-_. ])gemma[-_ ]?3(?=$|[-_. ])"),
    ("gemma4", r"(?:^|[-_. ])gemma[-_ ]?4(?=$|[-_. ])"),
    ("llama3", r"(?:^|[-_. ])llama[-_ ]?3(?:\.[0-9]+)?(?=$|[-_. ])"),
    ("qwen25", r"(?:^|[-_. ])qwen[-_ ]?2[._]?5(?=$|[-_. ])"),
    ("qwen3", r"(?:^|[-_. ])qwen[-_ ]?3(?:\.[0-9]+)?(?=$|[-_. ])"),
    ("phi", r"(?:^|[-_. ])phi[-_ ]?[34](?:\.[0-9]+)?(?=$|[-_. ])"),
    ("mistral", r"(?:^|[-_. ])(?:mistral|mixtral)(?=$|[-_. 0-9])"),
    ("lfm", r"(?:^|[-_. ])lfm[-_ ]?[23](?=$|[-_. ])"),
    ("smollm", r"(?:^|[-_. ])smollm[123]?(?=$|[-_. ])"),
    ("granite", r"(?:^|[-_. ])granite(?=$|[-_. 0-9])"),
    ("deepseek", r"(?:^|[-_. ])deepseek(?=$|[-_. ])"),
    ("glm", r"(?:^|[-_. ])glm(?=$|[-_. 0-9])"),
))

# field: (llama-server flag, minimum, maximum, integer, exclusive minimum)
_OPTIONS = {
    "temp": ("--temp", 0, 1, False, True),
    "top_p": ("--top-p", 0, 1, False, True),
    "top_k": ("--top-k", 1, 200, True, False),
    "min_p": ("--min-p", 0, 1, False, False),
    "repeat_penalty": ("--repeat-penalty", 1, 1.3, False, False),
    "repeat_last_n": ("--repeat-last-n", 16, 2048, True, False),
    "dry_multiplier": ("--dry-multiplier", 0, 2, False, False),
    "dry_base": ("--dry-base", 1, 3, False, True),
    "dry_allowed_length": ("--dry-allowed-length", 2, 16, True, False),
    "dry_penalty_last_n": ("--dry-penalty-last-n", 16, 2048, True, False),
    "n_predict": ("-n", 1, 1024, True, False),
}


def _number(field: str, value: str | int | float, source: str) -> int | float:
    _, low, high, integer, exclusive = _OPTIONS[field]
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
        if (not math.isfinite(number) or number > high or number < low
                or (exclusive and number == low) or (integer and not number.is_integer())):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        # No raw values: a mistyped environment value could contain private text.
        interval = f"{'(' if exclusive else '['}{low}, {high}]"
        raise RuntimeError(f"{source} must be {'an integer' if integer else 'a number'} in {interval}") from None
    return int(number) if integer else number


def generation_profile(model_path: str | Path, profile: str | None = None,
                       overrides: Mapping[str, int | float] | None = None,
                       environ: Mapping[str, str] | None = None) -> GenerationProfile:
    """Resolve family -> hardware profile -> explicit settings -> environment.

    Explicit/environment settings remain bounded; -1 (unlimited) is refused.
    This resolves settings only: it never reads a model or starts a runtime.
    """
    name = str(model_path).replace("\\", "/").rsplit("/", 1)[-1]
    # Distilled names can contain several families; the first named family wins
    # (e.g. DeepSeek-R1-Distill-Llama-3.3), regardless of table ordering.
    matches = ((match.start(), key) for key, pattern in _FAMILIES
               if (match := pattern.search(name)))
    family = min(matches, default=(0, "generic"))[1]
    result = GENERATION_PROFILES[family]
    if profile == "rx580-old-mac":
        result = replace(result, temp=min(result.temp, 0.3),
                         repeat_penalty=max(result.repeat_penalty, 1.15),
                         dry_multiplier=max(result.dry_multiplier, 0.8),
                         n_predict=min(result.n_predict, 384))
    changes: dict[str, int | float] = {}
    for field, value in (overrides or {}).items():
        if field not in _OPTIONS:
            raise RuntimeError("Unknown generation override field")
        if not isinstance(value, (int, float)):
            raise RuntimeError(f"generation override {field} must be numeric")
        changes[field] = _number(field, value, f"generation override {field}")
    env = os.environ if environ is None else environ
    for field in _OPTIONS:
        key = "OPOS_GPU_LINK_" + field.upper()
        if key in env:
            changes[field] = _number(field, env[key], key)
    return replace(result, **changes)


def generation_flags(model_path: str | Path, profile: str | None = None,
                     overrides: Mapping[str, int | float] | None = None,
                     environ: Mapping[str, str] | None = None) -> list[str]:
    """Sampling defaults for every backend; GGUF EOG tokens remain enabled.

    Do not add --reverse-prompt as a substitute for an HTTP stop list, or guess
    a --chat-template from a filename. The runtime owns both from GGUF metadata.
    """
    settings = generation_profile(model_path, profile, overrides, environ)
    flags: list[str] = []
    for field, (flag, *_rest) in _OPTIONS.items():
        flags.extend((flag, str(getattr(settings, field))))
    return flags
