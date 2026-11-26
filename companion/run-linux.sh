#!/usr/bin/env bash
# Start the headless companion with remembered trust. Repeatable --extra-model
# entries pass through in "$@". No installs.
set -eu
cd -- "$(dirname -- "$0")"

python=${OPOS_GPU_LINK_PYTHON:-python3}
if [[ -z "${OPOS_GPU_LINK_PYTHON:-}" ]] && ! command -v python3 >/dev/null 2>&1 && [[ -x /usr/bin/python3 ]]; then
    python=/usr/bin/python3
fi
adb=adb
if ! command -v adb >/dev/null 2>&1; then
    for candidate in "${HOME}/Android/Sdk/platform-tools/adb" /usr/bin/adb; do
        if [[ -f "$candidate" && -x "$candidate" ]]; then
            adb=$candidate
            break
        fi
    done
fi

# argparse takes the last --adb value, so an explicit override wins.
exec "$python" -B opos_gpu_link.py --headless --always-allow --adb "$adb" "$@"
