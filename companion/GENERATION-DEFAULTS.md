# Generation defaults

These conservative demo presets reduce garbage; they do not eliminate garbage
or hallucinations. They are starting points, not measured per-model quality
results or vendor-recommended benchmark settings. Every pinned model in
`gpu_link_pins.py`, including the RX 580 catalog, resolves to a named preset.
Local models are matched by filename, case-insensitively; unknown files use
`generic`. Parent directory names do not select a family.
If a distilled filename names several families, the first family token wins
(for example, `DeepSeek-R1-Distill-Llama-3.3` selects DeepSeek).

| Family / local filename | Temp | Top-p | Top-k | Min-p | Repeat penalty | Max new tokens | Rationale |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Gemma 3 / `gemma-3`, `gemma3` | 0.5 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Moderate variety with a demo-length answer budget. |
| Gemma 4 / `gemma-4`, `gemma4` | 0.5 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Same cautious starting point; native quality unverified. |
| Llama 3.x / `llama-3.2` etc. | 0.5 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Bound small instruct models before long repetitions develop. |
| Qwen 2.5 / `qwen2.5` | 0.4 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Lower variety for the older RX 580 catalog family. |
| Qwen 3.x / `qwen3`, `qwen3.6` etc. | 0.6 | 0.95 | 20 | 0.00 | 1.10 | 1024 | Slightly more variety and room within a bounded budget. |
| Phi 3.x / 4.x / `phi-4-mini` etc. | 0.4 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Favor concise, stable small-model answers. |
| Mistral / Mixtral | 0.5 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Moderate sampling without assuming a template version. |
| LFM 2.x / 3.x | 0.3 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Cautious sampling for small companion lanes. |
| SmolLM 1 / 2 / 3 | 0.4 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Bound small local answerers. |
| Granite | 0.4 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Conservative local-family fallback. |
| DeepSeek | 0.5 | 0.90 | 40 | 0.05 | 1.10 | 1024 | More budget for reasoning-capable files, still finite. |
| GLM | 0.5 | 0.90 | 40 | 0.05 | 1.10 | 1024 | More budget for reasoning-capable files, still finite. |
| Generic / unknown | 0.4 | 0.90 | 40 | 0.05 | 1.10 | 1024 | Conservative settings without guessing model identity. |

The 1024-token budget is meant for a short live demo: on a warm mid-size local model it is roughly a dozen to fifteen seconds of generation, long enough for a complete answer without filling a five-minute show. The `rx580-old-mac` overlay still caps new tokens at 384. The phone UI trims a finished length-capped answer to the last complete sentence so it does not show a hanging clause; the stored text and USB acks stay exact.

All rows use a 128-token repetition window, DRY multiplier `0.6`, base `1.75`,
allowed length `4`, and a 128-token DRY window. DRY's existing sequence breakers
remain unchanged. Repetition penalties may also discourage legitimate repeats
in code, lists, or tables; these values need real prompt testing.

The `rx580-old-mac` hardware profile overlays temperature at most `0.3`, repeat
penalty at least `1.15`, DRY multiplier at least `0.8`, and at most `384` new
tokens. It keeps the existing `-fa off --no-kv-offload`, context, layer offload,
device selection, and model filtering. All other backends (Metal, CUDA, Vulkan,
CPU, and CPU fallback) use the same family resolver through `server_command()`.

Every family uses its actual GGUF end-of-generation tokens (EOS / end of turn)
and embedded Jinja chat template. There is no guessed string stop list or
`--chat-template` override, including for unknown files. No catalog file is
currently established here as needing a template repair. This avoids applying
one family's end-token spelling to another GGUF. Missing/bad GGUF metadata is
not repaired by this change and needs a separately verified model-specific fix.
`--reverse-prompt` is not used as an HTTP stop-list substitute. The pinned
[server documentation](https://github.com/ggml-org/llama.cpp/blob/b12682/tools/server/README.md)
describes request `stop` arrays separately from interactive reverse prompts.

Settings resolve in this order: family, hardware profile, explicit
`generation_overrides` in `server_command()`, then environment. Environment
values apply when the launcher builds each new command. They do not reconfigure
an existing server. Supported overrides are:

- `OPOS_GPU_LINK_TEMP`: number in `(0, 1]`.
- `OPOS_GPU_LINK_TOP_P`: number in `(0, 1]`.
- `OPOS_GPU_LINK_TOP_K`: integer in `[1, 200]`.
- `OPOS_GPU_LINK_MIN_P`: number in `[0, 1]`.
- `OPOS_GPU_LINK_REPEAT_PENALTY`: number in `[1, 1.3]`.
- `OPOS_GPU_LINK_REPEAT_LAST_N`: integer in `[16, 2048]`.
- `OPOS_GPU_LINK_DRY_MULTIPLIER`: number in `[0, 2]`; `0` disables DRY.
- `OPOS_GPU_LINK_DRY_BASE`: number in `(1, 3]`.
- `OPOS_GPU_LINK_DRY_ALLOWED_LENGTH`: integer in `[2, 16]`.
- `OPOS_GPU_LINK_DRY_PENALTY_LAST_N`: integer in `[16, 2048]`.
- `OPOS_GPU_LINK_N_PREDICT`: integer in `[1, 1024]`; unlimited values are refused.

For example, `OPOS_GPU_LINK_TEMP=0.25 OPOS_GPU_LINK_N_PREDICT=256 ./start-mac.command`
uses a lower temperature and shorter budget. Explicit overrides use the same
lowercase field names as the environment suffixes, such as
`generation_overrides={"temp": 0.25, "n_predict": 256}`. Invalid settings stop
command construction with a named error; their raw values are not printed.
Explicit/environment settings can override the RX 580 sampling overlay within
the documented bounds. The existing RX 580 runtime quirks remain enabled.

The generated command emits `--temp`, `--top-p`, `--top-k`, `--min-p`,
`--repeat-penalty`, `--repeat-last-n`, `--dry-multiplier`, `--dry-base`,
`--dry-allowed-length`, `--dry-penalty-last-n`, and `-n`. These spellings were
checked read-only against the local pinned llama-server build 12682
(`b12f22d2f`) on 2026-11-25 with `--help` and `--version`; no model was loaded.
The older installed Metal build 11671 also lists these options. The separately
pinned no-AVX RX 580 executable was not executed or connected to.

These are defaults for launcher-owned servers. HTTP requests can supply
sampling parameters; this branch does not change request construction or add a
request-side stop list. Existing/LM Studio servers are unaffected. Native
inference, truncation behavior, answer quality, template correctness, and
cross-platform executable behavior remain unverified by the unit tests.
