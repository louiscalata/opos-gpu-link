# OPOS GPU Link

**Put your phone to good use: private AI, right in your pocket.**

Ask on your Android phone. A model on your computer and models on your phone can answer the same question. Each answer gets its own card and appears as it is written. The computer link uses a USB-C cable. Wireless: coming later.

## What you need

- An Android phone, a computer with a GPU, and a USB-C data cable. The Dec 10, 2026 show uses a Galaxy Z Flip 6 and an M5 Pro MacBook Pro.
- For this checkout's interface, [build the phone app](CONTRIBUTING.md#build-the-apk) and install `android/app/build/outputs/apk/debug/app-debug.apk`. The [Releases](https://github.com/louiscalata/opos-gpu-link/releases) APK is an earlier demo build. The phone-side service is described in [phone-service/README.md](phone-service/README.md).
- [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) on the computer, with USB debugging enabled on the phone.
- A local model file and a local `llama-server` program on the computer before you start offline. See [computer setup](companion/SETUP.md). Offline startup cannot download missing files.

## Quick start

1. Install the phone app and start the phone-side service on the phone. The APK needs that service running. If you use this repository's stand-alone service, copy `phone-service/` to the phone and follow [its guide](phone-service/README.md).
2. Connect the phone to the computer with the USB-C cable. Unlock the phone and allow its USB debugging prompt.
3. On the computer, start the companion from the checkout root. Replace the model path with a file already on your computer:

   ```sh
   python3 companion/gpu_link_autosetup.py --offline --strict-ports --own-server --no-extras --port 38400 --model-path /path/to/model.gguf
   ```

4. Compare the six-digit code on the phone and computer. If the codes match, tap **Allow** on the phone. The phone remembers that computer for later plugs.
5. Ask a question on the phone. Watch each ready model's answer appear on its own card.

The companion starts its own local model server and skips other model apps. `--offline` prevents downloads, and `--no-extras` shows one computer answer card. The number 38400 is the first local connection number it tries for its server. `--model-path` names the file to prefer; if that file is missing, the companion may choose another local file. Check the model name it shows at startup. The [computer companion guide](companion/README.md) covers other systems and setups.

## What you will see

The Dec 10 show is a newspaper-style front page: one card for each model answer, with text appearing live. The demo phone and MacBook use these models today. The stand-alone phone service in this repo can show one phone answer from a local model server; the `m1`–`m4` cards need the full OPOS phone app and its local model files.

| Card | Model | Maker | Role |
| --- | --- | --- | --- |
| Computer | Nemotron 3.5 Bolt | NVIDIA | Primary; runs on the computer GPU |
| Phone `m1` | Nemotron Mini 4B | NVIDIA | Phone model |
| Phone `m2` | Qwen3.5-2B | Qwen (Alibaba) | Phone model |
| Phone `m3` | LFM2 1.2B (baseline) | Liquid AI | Baseline (comparison) |
| Phone `m4` | Granite 4.1 3B | IBM | Phone model |

Nemotron 3.5 Bolt is post-trained by NVIDIA from Google's Gemma 4 E4B, so Gemma's terms also apply. On a MacBook, Bolt runs on Apple's GPU through Metal, not on an NVIDIA GPU.

The model files for Qwen3.5-2B and Granite 4.1 3B are not listed in this repository. Their file sizes and hashes have not been recorded here.

## Stop and unplug

If you unplug the cable, the computer answer pauses and keeps the text already shown. Phone answers can continue. Replug while the companion is still running to reconnect and continue the computer answer; the rest of the answer may differ from an uninterrupted run. Press Ctrl-C in the companion terminal to stop the run and remove its USB link. Pairing stays saved until you choose to forget it.

## Troubleshooting

- **Phone not found:** use a data cable, unlock the phone, and allow its USB debugging prompt. See [computer setup](companion/SETUP.md) if more than one phone is connected.
- **Codes differ:** do not tap Allow. Check that you are comparing the same phone and computer, then start pairing again.
- **Model will not start:** check that the local model file and server program are present. Offline mode will not download them. See [computer setup](companion/SETUP.md).
- **App stays on Home after an update:** After replacing the app on a Samsung phone, the first start can leave the Home screen showing. Unlock the phone and open OPOS GPU Link from its icon. Check that the app is on screen before the demo; a finished start command does not confirm it opened.
- **Answer stays paused after replug:** leave the companion running and check the cable and USB debugging approval. See [unplugging and troubleshooting](companion/SETUP.md#unplugging-and-troubleshooting).

## Privacy

Questions and answers are visible to your phone and your own computer. The computer model runs locally. With the offline quick start above, the companion does not download files or send your questions to a cloud service. The phone app talks to its own local service; the companion reaches the phone service through a USB-C `adb` forward. Requests after pairing are signed.

## Recorded model files (27 Nov 2026)

These file details were recorded on the demo MacBook on 27 Nov 2026 (America/Los_Angeles). Sizes and recorded SHA-256 values were computed with `shasum -a 256` from those files. Qwen3.5-2B and Granite 4.1 3B have no recorded size or SHA-256 here.

| Where | Model | File | Size | SHA-256 | License |
| --- | --- | --- | --- | --- | --- |
| MacBook (Metal) | [NVIDIA Nemotron 3.5 Bolt E4B 4GB, Q4_K_M](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB) | `Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf` | 6.18 GB (6,180,446,208 bytes) | `c8af2b8aea10a690a1d9491db744a9446660173cb38fc489612b556615a69612` | OpenMDW-1.1 |
| Phone `m1` | [NVIDIA Nemotron Mini 4B Instruct, Q4_K_M](https://huggingface.co/bartowski/Nemotron-Mini-4B-Instruct-GGUF) (community quant) | `Nemotron-Mini-4B-Instruct-Q4_K_M.gguf` | 2.70 GB (2,697,387,072 bytes) | `2bf02846dbd45e9580b9338b90505fb54e00d185713d4b7f06699e2d5d298e48` | NVIDIA Open Model License |
| Phone `m3` (baseline) | [LFM2 1.2B (Liquid AI)](https://huggingface.co/LiquidAI/LFM2-1.2B-GGUF) | `LFM2-1.2B-Q4_K_M.gguf` | 0.73 GB (730,893,248 bytes) | `55175400e3f509a9616227afeffd58d87e80b9f628a5d3d54ada884d85221fed` | [LFM Open License v1.0](https://huggingface.co/LiquidAI/LFM2-1.2B-GGUF/blob/main/LICENSE) |

### Earlier lineup

These files were also recorded on 27 Nov 2026. They are not in the current demo lineup.

| Where | Model | File | Size | SHA-256 | License |
| --- | --- | --- | --- | --- | --- |
| Phone, former lead | [NVIDIA AceInstruct 1.5B, Q4_K_M](https://huggingface.co/bartowski/nvidia_AceInstruct-1.5B-GGUF) (community quant) | `nvidia_AceInstruct-1.5B-Q4_K_M.gguf` | 1.12 GB (1,117,318,944 bytes) | `103b7fa617d2b3c2d6e168a878b9b5e3710d19d178bf4b890acf0fac2abafadb` | CC-BY-NC-4.0 |
| MacBook, comparison only | [Gemma 4 26B (Google)](https://huggingface.co/google/gemma-4-26B-A4B-it-qat-q4_0-gguf) | `gemma-4-26B_q4_0-it.gguf` | 14.44 GB (14,439,363,584 bytes) | Not recorded | Apache-2.0 |

Gemma was a measured baseline and rollback. Gemma's SHA-256 was not recorded while LM Studio was serving it.

## Supported platforms

| | |
| --- | --- |
| Phone | Android 10+ (tested on a Galaxy Z Flip 6, inner and cover screens) |
| macOS | Apple silicon (Metal), Intel with a Vulkan GPU |
| Windows | x86_64, NVIDIA (CUDA) or AMD/Intel (Vulkan) |
| Linux | x86_64, NVIDIA (CUDA) or Vulkan |

## Status

Early demo build. USB is the only link today. Wireless: coming later.

- The APK is a debug build signed with a throwaway key. It is not on Google Play.
- The phone side runs on its own with `phone-service/run_link.py`, including the `/api/ai` endpoint the app reads. To give a phone answer, it needs a local model server on the phone, such as `llama-server`. Without one, questions go to the computer.
- Hands-on checks for a live Galaxy Z Flip 6 and MacBook (screens, Stop, cable pull, copy, soak, rehearsals, screenshots) are in [HANDS-ON-RUNSHEET.md](HANDS-ON-RUNSHEET.md).

OPOS GPU Link is part of the early Old Phone OS project, coming soon.

## License

Apache-2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE) and [THIRD_PARTY.md](THIRD_PARTY.md). To report a vulnerability, see [SECURITY.md](SECURITY.md). To open an issue or a pull request, see [CONTRIBUTING.md](CONTRIBUTING.md).
