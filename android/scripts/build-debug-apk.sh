#!/usr/bin/env bash
set -euo pipefail

# Direct SDK-tool debug build (no Gradle daemon). Needs JDK 17 and an Android SDK
# with platform android-37.0 and build-tools 37.0.0.
#   JAVA_HOME=/path/to/jdk17 ANDROID_SDK_ROOT=/path/to/sdk ./scripts/build-debug-apk.sh
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT"
: "${JAVA_HOME:?set JAVA_HOME to a JDK 17}"
ANDROID_SDK="${ANDROID_SDK_ROOT:?set ANDROID_SDK_ROOT to your Android SDK}"
ANDROID_JAR="$ANDROID_SDK/platforms/android-37.0/android.jar"
BUILD_TOOLS="$ANDROID_SDK/build-tools/37.0.0"
WORK="$PROJECT/.build-tmp/plug-and-play"
OUTPUT="$PROJECT/app/build/outputs/apk/debug"

rm -rf "$WORK"
mkdir -p "$WORK/compiled" "$WORK/generated" "$WORK/classes" "$WORK/dex" "$OUTPUT"
python3 - "$WORK/AndroidManifest.xml" <<'PY'
from pathlib import Path
import sys

source = Path("app/src/main/AndroidManifest.xml").read_text()
old = '<manifest xmlns:android='
assert source.count(old) == 1 and 'package=' not in source.splitlines()[0]
Path(sys.argv[1]).write_text(source.replace(
    old, '<manifest package="os.opos.launcher" xmlns:android=', 1
))
PY

"$BUILD_TOOLS/aapt2" compile --dir app/src/main/res -o "$WORK/compiled"
"$BUILD_TOOLS/aapt2" link --debug-mode \
    -o "$WORK/resources.apk" -I "$ANDROID_JAR" \
    --manifest "$WORK/AndroidManifest.xml" \
    --java "$WORK/generated" \
    --min-sdk-version 29 --target-sdk-version 36 \
    --version-code 1 --version-name 1.0 \
    -R "$WORK"/compiled/*.flat

find app/src/main/java -name '*.java' -print0 |
    xargs -0 "$JAVA_HOME/bin/javac" -encoding UTF-8 -source 17 -target 17 \
    -cp "$ANDROID_JAR" -d "$WORK/classes" \
    "$WORK/generated/os/opos/launcher/R.java"

find "$WORK/classes" -name '*.class' -print0 |
    xargs -0 "$BUILD_TOOLS/d8" --lib "$ANDROID_JAR" --output "$WORK/dex"
cp "$WORK/resources.apk" "$WORK/unsigned.apk"
(cd "$WORK" && zip -q -j unsigned.apk dex/classes.dex)
"$BUILD_TOOLS/zipalign" -f 4 "$WORK/unsigned.apk" "$WORK/aligned.apk"
"$BUILD_TOOLS/apksigner" sign --ks "${DEBUG_KEYSTORE:-$HOME/.android/debug.keystore}" \
    --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android \
    --out "$OUTPUT/app-debug.apk" "$WORK/aligned.apk"
"$BUILD_TOOLS/apksigner" verify --verbose --print-certs "$OUTPUT/app-debug.apk"
"$BUILD_TOOLS/aapt2" dump badging "$OUTPUT/app-debug.apk"
shasum -a 256 "$OUTPUT/app-debug.apk"
