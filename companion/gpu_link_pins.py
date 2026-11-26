# SPDX-License-Identifier: Apache-2.0
"""Pinned SHA-256 checksums for everything the plug-and-play launcher downloads.

llama.cpp: the GitHub release digests for tag b12682, each re-computed by downloading the file.
Platform-tools: Google r37.0.3 zips, hashed here at pin time. Models: Hugging Face LFS object ids (= SHA-256),
sizes from the Hub. A download that does not match is discarded and never used.
To update: change the values here (and LLAMA_TAG) together; see PLUG-AND-PLAY.md.
Qwen3-1.7B-Q8_0.gguf (the only GGUF in the official Qwen/Qwen3-1.7B-GGUF repo) was
re-downloaded from Hugging Face on 2026-11-25 and SHA-256-verified as
061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a (1,834,426,016 bytes).
"""

LLAMA_TAG = "b12682"

LLAMA = {
    "llama-b12682-bin-ubuntu-cuda-12.8-x64.tar.gz": {"sha256": "9d758bab0360dbae08e066bf5c66a86417fff946399b14dd75d557b6f42d4326", "size": 220407203},
    "cudart-llama-b12682-bin-ubuntu-cuda-12.8-x64.tar.gz": {"sha256": "f425bc1c381f6f866a5214222659ff6619d63086300b1478c8bdf0b580a17518", "size": 594376831},
    "llama-b12682-bin-macos-arm64.tar.gz": {"sha256": "da3b6d5edbc9891497f7c48bf9821d32e83b2852226a81f64d50ea2e331a181b", "size": 16820286},
    "llama-b12682-bin-macos-x64.tar.gz": {"sha256": "e952e1943719e656eb68c6180814a772a633820a842d58251bf9b9a4f6e33777", "size": 12540823},
    "llama-b12682-bin-ubuntu-x64.tar.gz": {"sha256": "74f1ce0be97a5ce7addf1be69ad7d27db3aab70f4ce07fb1caebba51c83d2768", "size": 23377984},
    "llama-b12682-bin-ubuntu-vulkan-x64.tar.gz": {"sha256": "e04eb17d34b9e784e043fb0f0388b759188b1cb7d2a406a5dbeaaf84f7a8b234", "size": 37074818},
    "llama-b12682-bin-ubuntu-arm64.tar.gz": {"sha256": "65acb1da0958857d8b1257c28ecdd1057d9559eb9a1941a909efc88d8824e25a", "size": 18929324},
    "llama-b12682-bin-ubuntu-vulkan-arm64.tar.gz": {"sha256": "8eed5beae8269efdb449ace818e200980f1d74143bfedebdf3e5af4f61fd8da4", "size": 30058249},
    "llama-b12682-bin-win-cuda-12.4-x64.zip": {"sha256": "39460d1054bc2bc4fe8a2668297e9cc06e3d95b081287770ae0933d0e38ef902", "size": 358337518},
    "llama-b12682-bin-win-cuda-13.5-x64.zip": {"sha256": "4aa0308a21c10cf20e9c0aafd8330e5f50d2d2271c091143939be1de193bd359", "size": 225953052},
    "cudart-llama-bin-win-cuda-12.4-x64.zip": {"sha256": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6", "size": 391443627},
    "cudart-llama-bin-win-cuda-13.5-x64.zip": {"sha256": "c2bf4cc202bfbaaa7a0b75f5082457c3811326947bb216059b72839d844e9cba", "size": 426314199},
    "llama-b12682-bin-win-vulkan-x64.zip": {"sha256": "552feae09e086c19d8f26f598d023218e30be32c38bd1c5e836042da1ed93fea", "size": 39076575},
    "llama-b12682-bin-win-cpu-x64.zip": {"sha256": "f5ca9510c54e8b04c752a980a6ffc93ea0f52d78bee41cac05c9cc55745b5757", "size": 25216426},
    "llama-b12682-bin-win-cpu-arm64.zip": {"sha256": "312513963117eca5ca5dabcd4cbb020e91dd542ad64c292ab921e79842658aef", "size": 13284487},
}

PLATFORM_TOOLS = {
    "linux": {"url": "https://dl.google.com/android/repository/platform-tools_r37.0.3-linux.zip", "sha256": "214548146cadb2ca3508143d8a1d4be4c59de5bb837253e3ede89ed74cf450d1", "size": 9571024},
    "darwin": {"url": "https://dl.google.com/android/repository/platform-tools_r37.0.3-darwin.zip", "sha256": "df21339b9371fef9b19264404338dc686f59a88a1dce634b963da344909001d6", "size": 16597626},
    "windows": {"url": "https://dl.google.com/android/repository/platform-tools_r37.0.3-win.zip", "sha256": "89d108360a3bf2924d3bea837239edaccc22fd6ff5befd3787c4348a9fe4f09d", "size": 8188601},
}

MODELS = (
    {"role": "main", "repo": "ggml-org/gemma-3-27b-it-GGUF", "file": "gemma-3-27b-it-Q4_K_M.gguf", "size": 16546404736, "sha256": "edc9aff4d811a285b9157618130b08688b0768d94ee5355b02dc0cb713012e15", "label": "Gemma 3 27B", "maker": "Google"},
    {"role": "main", "repo": "ggml-org/gemma-3-12b-it-GGUF", "file": "gemma-3-12b-it-Q4_K_M.gguf", "size": 7300574976, "sha256": "7bb69bff3f48a7b642355d64a90e481182a7794707b3133890646b1efa778ff5", "label": "Gemma 3 12B", "maker": "Google"},
    {"role": "main", "repo": "ggml-org/gemma-3-4b-it-GGUF", "file": "gemma-3-4b-it-Q4_K_M.gguf", "size": 2489757856, "sha256": "882e8d2db44dc554fb0ea5077cb7e4bc49e7342a1f0da57901c0802ea21a0863", "label": "Gemma 3 4B", "maker": "Google"},
    {"role": "main", "repo": "ggml-org/gemma-3-1b-it-GGUF", "file": "gemma-3-1b-it-Q4_K_M.gguf", "size": 806058240, "sha256": "8ccc5cd1f1b3602548715ae25a66ed73fd5dc68a210412eea643eb20eb75a135", "label": "Gemma 3 1B", "maker": "Google"},
    {"role": "extra", "repo": "Qwen/Qwen3-4B-GGUF", "file": "Qwen3-4B-Q4_K_M.gguf", "size": 2497280256, "sha256": "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5", "label": "Qwen3 4B", "maker": "Qwen"},
    {"role": "extra", "repo": "Qwen/Qwen3-1.7B-GGUF", "file": "Qwen3-1.7B-Q8_0.gguf", "size": 1834426016, "sha256": "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a", "label": "Qwen3 1.7B", "maker": "Qwen"},
    {"role": "extra", "repo": "LiquidAI/LFM2-2.6B-GGUF", "file": "LFM2-2.6B-Q4_K_M.gguf", "size": 1563668704, "sha256": "384bc877b6c37064982f96885bef69e4475919f5969218ed4e3b9399ae0340df", "label": "LFM2 2.6B", "maker": "Liquid AI"},
    {"role": "extra", "repo": "LiquidAI/LFM2-1.2B-GGUF", "file": "LFM2-1.2B-Q4_K_M.gguf", "size": 730893248, "sha256": "55175400e3f509a9616227afeffd58d87e80b9f628a5d3d54ada884d85221fed", "label": "LFM2 1.2B", "maker": "Liquid AI"},
)

# "RX 580 / old Mac" profile (Polaris AMD GPU on an Intel Mac via MoltenVK, measured on the Mac Pro 5,1):
# only Q8_0 files of these families return correct text on the GPU. Q4_0/Q4_K/Q5_K/Q6_K/F16, Gemma 3 and
# Qwen3 return blank or junk. SHA-256 are of the files the receipts were measured with (hashed at pin time).
RX580_MODELS = (
    {"role": "main", "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF", "file": "qwen2.5-1.5b-instruct-q8_0.gguf", "size": 1894532128, "sha256": "d7efb072e7724d25048a4fda0a3e10b04bdef5d06b1403a1c93bd9f1240a63c8", "label": "Qwen2.5 1.5B", "maker": "Qwen"},
    {"role": "extra", "repo": "bartowski/Llama-3.2-1B-Instruct-GGUF", "file": "Llama-3.2-1B-Instruct-Q8_0.gguf", "size": 1321083008, "sha256": "432f310a77f4650a88d0fd59ecdd7cebed8d684bafea53cbff0473542964f0c3", "label": "Llama 3.2 1B", "maker": "Meta"},
)


# Intel Mac (x86_64) WITHOUT AVX, e.g. a Mac Pro 5,1 with an RX 580: the official macOS x64 llama.cpp has no
# Vulkan/MoltenVK and needs AVX, so GPU Link ships its own build. It is llama.cpp a91eab6 built with
# -DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DGGML_AVX=OFF (SSE4.2) plus MoltenVK and the Vulkan loader from the LunarG
# SDK, with relative loader paths and ad-hoc signed (companion/pack_noavx_vulkan.py). The .tar.gz is packed INTO
# the Darwin-x86_64 bundle (build_bundle.py --noavx-vulkan) and checked against this SHA-256 before it is
# unpacked; every unpacked file is checked against "files" each run. "url" is an optional mirror
# (None = bundle only, nothing is fetched); a mirror download is also refused unless it matches the SHA-256.
# Written by `pack_noavx_vulkan.py --pins gpu_link_pins.py` (see PLUG-AND-PLAY.md, "Intel Mac without AVX").
# This must stay the last statement of the file.
NOAVX_VULKAN_MACOS_X64 = {
    "dir": "llama-a91eab6-macos-x64-vulkan-noavx",
    "files": {
        "NOTICE.txt": "e4816d2e47c794c8a2659182ebe2cb2447e24c46e42c0675d8adfb99283a81f3",
        "bin/libggml-base.0.dylib": "916fd2d4df67050b92134537001c76d8638210d2652db0746160364c378a6fa1",
        "bin/libggml-cpu.0.dylib": "77e4c872ff65a840de4a5f66c35b0cef0e18edb76688271ba8c3da057f950993",
        "bin/libggml-vulkan.0.dylib": "b8bd0f9d47ba0687bf879876c5d14dbfec1c2cb3f9683d84c0e6058450db470b",
        "bin/libggml.0.dylib": "77b907197f44de611c58861622e660a0f3624e830fbe8d87ad7ae21848734f99",
        "bin/libllama-common.0.dylib": "89164b34327c706fd6c942b349cb017603d55f2e7c697f9ef37ef65098896773",
        "bin/libllama-server-impl.dylib": "9abf14271ecc9c242f52a74f5e0e61c239aeab26884f7e7c961d9bf9b434b804",
        "bin/libllama.0.dylib": "acb6ae9d05e73ed85b35a04b0bc1c66d9977589fa9d56b529ffd6b57087dd6b5",
        "bin/libmtmd.0.dylib": "10992e3e3a00c2783807d9418ee229fc7d8acbb4c994c0bbf6292b5cbaa63f63",
        "bin/llama-server": "362b1714bf624ec9a7fb36e6ff08ce780a1bc9d05829adc528269ff7ff543c01",
        "lib/libMoltenVK.dylib": "8f4effc02ccc1f6f0253cca1e0aa98f61fdeeca4a7006dc314c7701e223290da",
        "lib/libvulkan.1.dylib": "a3da59d480bde1cdffee463d3a7e9bfb4efe55afbdd88a38bf2528c33aa057c4",
        "share/vulkan/icd.d/MoltenVK_icd.json": "9d4632ab0f6c32f6627a7c669d6734701786e974fbe8c25bb892aca4a21c2a26"
    },
    "name": "llama-a91eab6-macos-x64-vulkan-noavx.tar.gz",
    "sha256": "643473dcbc0e1d7e0e4eca0435fa9d86eb610b2a6535078d17277604581cf7e1",
    "size": 27453457,
    "url": None
}
