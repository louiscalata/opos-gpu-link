# OPOS GPU Link

**Put your phone to good use: private AI, right in your pocket.**

Small models run on your phone; bigger ones run on your own computer's GPU over a USB-C cable. No cloud.

Ask a question on your Android phone and read both answers side by side. Pull the cable and the GPU answer pauses. Plug it back in and it picks up where it left off.

```mermaid
flowchart LR
    A["Phone app<br/>ask · read · notes"] --> B["Phone link service<br/>127.0.0.1"]
    B <-->|"USB-C<br/>adb forward, signed"| C["PC companion"]
    C --> D["Local model server<br/>llama.cpp on your GPU"]
```

## Quick start

1. **adb.** Install Google's [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) for `adb`.
2. **PC.** Install Python 3.10+ and follow [`companion/SETUP.md`](companion/SETUP.md) to start the companion against a local model server. One-file PC apps for macOS, Windows and Linux are coming to [Releases](../../releases).
3. **Phone.** Turn on USB debugging, plug in the cable, accept the computer's prompt, and install the APK from [Releases](../../releases).
4. **Pair.** Compare the six-digit code on both screens and tap **Allow this PC** on the phone. Later plugs reuse that pairing.
5. **Ask.**

Build the app yourself with `android/scripts/build-debug-apk.sh`.

## What's here

| | |
| --- | --- |
| `android/` | The phone app |
| `phone-service/` | The phone side of the link: pairing, signed requests, pause and resume |
| `companion/` | The PC companion and its tests |

## Supported platforms

| | |
| --- | --- |
| Phone | Android 10+ (tested on a Galaxy Z Flip6, inner and cover screens) |
| macOS | Apple silicon (Metal), Intel with a Vulkan GPU |
| Windows | x86_64, NVIDIA (CUDA) or AMD/Intel (Vulkan) |
| Linux | x86_64, NVIDIA (CUDA) or Vulkan |

## Private

Private: runs on your phone and your own computer, no cloud.

- The PC companion downloads nothing by default. It uses models already on disk; fetching one is opt-in (`--prefetch`).
- The phone app talks only to its own loopback service. The PC is reached only through the USB forward.
- Every request is signed with a key set up when you pair.

## Status

Early demo build.

- The APK is a debug build signed with a throwaway key. It is not on Google Play.
- The phone side of the link is in `phone-service/`, but it still runs inside a host process that is not published yet. A standalone runner is next.
- The one-file PC apps are held back for now while `adb` is taken out of them.
- USB is the only link today. A wireless version is in the works.

OPOS GPU Link is part of the early Old Phone OS project, coming soon.

## License

Apache-2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE) and [THIRD_PARTY.md](THIRD_PARTY.md).
