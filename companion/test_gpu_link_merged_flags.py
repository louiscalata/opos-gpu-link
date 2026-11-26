# SPDX-License-Identifier: Apache-2.0
"""--gpu amd/intel (Windows branch) and --hide-nvidia (Linux branch) work together after the merge."""
import sys
import unittest

import gpu_link_autosetup as a
from test_gpu_link_autosetup import runner_for, which_only
import test_gpu_link_nonvidia as nv
from test_gpu_link_nonvidia import ARC, NVIDIA, RX, pci

NVIDIA_SMI = "NVIDIA GeForce RTX 5080, 16303, 15000, 575.51\n"


class MergedFlags(unittest.TestCase):
    setUp = nv.Detection.setUp
    card = nv.Detection.card

    def detect_only(self, table, only, *, environ=None, system="Linux"):
        run = runner_for(table)
        return a.detect_gpu(run, system, "x86_64", which_only(*table), only=only, environ=environ or {},
                            drm_root=self.root)

    @unittest.skipIf(sys.platform == "win32", "sysfs fixtures need ':' in directory names")
    def test_gpu_amd_ignores_nvidia_and_measures_sysfs_vram(self):
        self.card(0, "0x1002", "0000:03:00.0", vram_total=16384, vram_used=1024)
        table = {"nvidia-smi": NVIDIA_SMI, "lspci": pci(RX, "03:00.0") + pci(NVIDIA, "04:00.0")}
        auto = self.detect_only(table, "auto")
        self.assertEqual((auto["vendor"], auto["backend"]), ("NVIDIA", "cuda"))
        gpu = self.detect_only(table, "amd")
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["forced"]), ("AMD", "vulkan", "amd"))
        self.assertEqual((gpu["total_mb"], gpu["free_mb"]), (16384, 15360))
        self.assertEqual(gpu["budget_mb"], 15360 - a.VRAM_MARGIN_MB)
        self.assertNotIn("nvidia_hidden", gpu)

    def test_gpu_amd_with_no_amd_card_uses_cpu_not_nvidia(self):
        table = {"nvidia-smi": NVIDIA_SMI, "lspci": pci(NVIDIA, "04:00.0")}
        gpu = self.detect_only(table, "amd")
        self.assertEqual((gpu["backend"], gpu["forced"]), ("cpu", "amd"))

    @unittest.skipIf(sys.platform == "win32", "sysfs fixtures need ':' in directory names")
    def test_gpu_intel_picks_intel_over_amd(self):
        self.card(0, "0x1002", "0000:03:00.0", vram_total=16384, vram_used=0)
        table = {"lspci": pci(RX, "03:00.0") + pci(ARC, "04:00.0")}
        gpu = self.detect_only(table, "intel")
        self.assertEqual((gpu["vendor"], gpu["forced"]), ("Intel", "intel"))

    @unittest.skipIf(sys.platform == "win32", "sysfs fixtures need ':' in directory names")
    def test_hide_nvidia_alone_keeps_auto_choice_among_the_rest(self):
        self.card(0, "0x1002", "0000:03:00.0", vram_total=8192, vram_used=0)
        table = {"nvidia-smi": NVIDIA_SMI, "lspci": pci(RX, "03:00.0") + pci(NVIDIA, "04:00.0")}
        gpu = self.detect_only(table, "auto", environ={"OPOS_GPU_LINK_HIDE_NVIDIA": "1"})
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["nvidia_hidden"]), ("AMD", "vulkan", True))
        self.assertNotIn("forced", gpu)

    def test_hide_nvidia_with_gpu_nvidia_has_no_gpu(self):
        table = {"nvidia-smi": NVIDIA_SMI, "lspci": pci(NVIDIA, "04:00.0")}
        gpu = self.detect_only(table, "nvidia", environ={"OPOS_GPU_LINK_HIDE_NVIDIA": "1"})
        self.assertEqual(gpu["backend"], "cpu")

    @unittest.skipIf(sys.platform == "win32", "sysfs fixtures need ':' in directory names")
    def test_hide_nvidia_and_gpu_amd_together(self):
        self.card(0, "0x1002", "0000:03:00.0", vram_total=8192, vram_used=0)
        table = {"nvidia-smi": NVIDIA_SMI, "lspci": pci(RX, "03:00.0") + pci(NVIDIA, "04:00.0")}
        gpu = self.detect_only(table, "amd", environ={"OPOS_GPU_LINK_HIDE_NVIDIA": "1"})
        self.assertEqual((gpu["vendor"], gpu["forced"], gpu["nvidia_hidden"]), ("AMD", "amd", True))

    def test_gpu_cpu_still_wins_and_records_hidden(self):
        gpu = self.detect_only({}, "cpu", environ={"CUDA_VISIBLE_DEVICES": ""})
        self.assertEqual((gpu["backend"], gpu["forced"], gpu["nvidia_hidden"]), ("cpu", "cpu", True))


if __name__ == "__main__":
    unittest.main()
