#!/bin/bash
# Run: ./start-linux.sh   (or double-click "Run in terminal"). Finds the GPU (CUDA/Vulkan/CPU),
# a model and adb, then links the phone. Ctrl-C stops it and unloads the model.
cd "$(dirname "$0")" || exit 1
PY="${OPOS_GPU_LINK_PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3,10))' 2>/dev/null; then PY="$c"; break; fi
  done
fi
if [ -z "$PY" ]; then echo "GPU Link needs Python 3.10+ (e.g. sudo apt install python3)."; exit 1; fi
# Show-day default: --offline (no downloads). --prefetch is the at-home way to fetch.
offline_args=()
case " $* " in
  *" --prefetch "*) ;;
  *" --offline "*|*" --no-download "*) ;;
  *) offline_args=(--offline) ;;
esac
exec "$PY" -B gpu_link_autosetup.py "${offline_args[@]}" "$@"
