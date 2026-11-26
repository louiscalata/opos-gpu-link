#!/bin/sh
# Start the approved headless companion. Trailing flags, including repeatable
# --extra-model entries, pass through unchanged. No installs.
set -eu
cd "$(dirname "$0")"
exec "${OPOS_GPU_LINK_PYTHON:-python3}" -B opos_gpu_link.py --headless --always-allow "$@"
