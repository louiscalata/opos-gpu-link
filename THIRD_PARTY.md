# Third-party components

The source in this repository is Apache-2.0 (see `LICENSE` and `NOTICE`).
Some files and the release downloads include work by others under their own terms.

## In this repository

- **Fonts** in `android/app/src/main/res/font/`: Source Serif 4 (Adobe), Inter (The Inter Project Authors), Newsreader and JetBrains Mono, all under the SIL Open Font License 1.1. License texts and sources are in `android/third_party/fonts/`.

## In the one-file PC apps (when released)

They are built with PyInstaller and carry:

- **Python** runtime (PSF License).
- **PyInstaller** bootloader (GPL-2.0 with the bootloader exception, which allows distribution under any license).
- **llama.cpp** / `llama-server` (MIT), from the official ggml-org releases, pinned by SHA-256 in `companion/gpu_link_pins.py`. The Intel-Mac build carries a no-AVX Vulkan build with MoltenVK and the Khronos Vulkan loader (Apache-2.0).
- **NVIDIA CUDA runtime** libraries on Linux and Windows (redistributed as shipped in the llama.cpp CUDA release archives, under the NVIDIA CUDA Toolkit EULA).

`adb` is not bundled. Install Google's Android SDK Platform-Tools yourself; they are under Google's own terms.

No model weights are bundled. Models you download or point the app at keep their own licenses.
