#!/bin/bash
# Double-click in Finder. Opens Terminal, finds this Mac's GPU (Metal), a model and adb,
# then links the phone. Ctrl-C or closing the window stops it and unloads the model.
cd "$(dirname "$0")" || exit 1
PY="${OPOS_GPU_LINK_PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3,10))' 2>/dev/null; then PY="$c"; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "GPU Link needs Python 3.10 or newer. Install it from https://www.python.org/downloads/ and double-click again."
  read -r -p "Press Return to close." _; exit 1
fi
# Show-day default: --offline (no downloads). --prefetch is the at-home way to fetch.
offline_args=()
case " $* " in
  *" --prefetch "*) ;;
  *" --offline "*|*" --no-download "*) ;;
  *) offline_args=(--offline) ;;
esac
"$PY" -B gpu_link_autosetup.py "${offline_args[@]}" "$@"
code=$?
[ -t 0 ] && read -r -p "GPU Link stopped (code $code). Press Return to close." _
exit $code
