#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
JDK="${JAVA_HOME:?set JAVA_HOME to a JDK 17}"
OUT=.build-tmp/host-tests
rm -rf "$OUT"; mkdir -p "$OUT"
sources=()
for file in app/src/main/java/os/opos/launcher/*.java; do
  case "${file##*/}" in
    AiClient.java|AnswerMarkdown.java|BootReceiver.java|GpuLinkActivity.java|HingeProbe.java|LinedNotesEditText.java|LinkWatcherService.java|MainActivity.java|SendEditText.java|Typography.java) ;;
    *) sources+=("$file") ;;
  esac
done
"$JDK/bin/javac" --release 17 -encoding UTF-8 -d "$OUT" "${sources[@]}" tests/*.java
count=0
for file in tests/*Test.java; do
  class="${file##*/}"; class="${class%.java}"
  "$JDK/bin/java" -cp "$OUT" "os.opos.launcher.$class"
  count=$((count + 1))
done
echo "JAVA_CLASSES_PASSED=$count"
