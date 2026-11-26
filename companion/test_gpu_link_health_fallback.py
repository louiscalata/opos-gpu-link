# SPDX-License-Identifier: Apache-2.0
"""Fallback inventory policy tests: no model, network, GPU or server needed."""
from pathlib import Path
import threading
import unittest

from gpu_link_health import FallbackPlan, Model


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.large = Model("Qwen3 8B", 8000, Path("large.gguf"), available=True)
        self.small = Model("Qwen3 4B", 4000, Path("small.gguf"), available=True)
        self.other = Model("Llama 3.2 1B", 2000, Path("llama.gguf"), available=True)
        self.gemma = Model("Gemma 3 1B", 1000, Path("gemma.gguf"), available=True)

    def fail_twice(self, plan, original=None, lane="g1", question="q"):
        original = original or self.large
        self.assertIsNone(plan.record_failure(lane, question, original, "garbled"))
        return plan.record_failure(lane, question, original, "stream_error")

    def test_two_failures_return_smaller_model_with_honest_label(self):
        plan = FallbackPlan([self.small])
        replacement, label = self.fail_twice(plan)
        self.assertEqual(replacement, self.small)
        self.assertEqual(label, "Qwen3 4B (fallback for Qwen3 8B)")
        self.assertEqual(plan.failure_count("g1", "q"), 2)
        self.assertEqual(plan.status("g1"), "swapped")

    def test_first_failure_requests_retry(self):
        plan = FallbackPlan([self.small])
        self.assertEqual(plan.status("g1"), "ready")
        self.assertIsNone(plan.record_failure("g1", "q", self.large, "crash"))
        self.assertEqual(plan.status("g1"), "retry")

    def test_questions_are_independent(self):
        plan = FallbackPlan([self.small])
        for question in ("a", "b"):
            self.assertIsNone(plan.record_failure("g1", question, self.large, "model_start"))
        self.assertEqual(plan.failure_count("g1", "a"), 1)
        self.assertEqual(plan.failure_count("g1", "b"), 1)
        self.assertEqual(plan.failure_count("g1", "unseen"), 0)
        self.assertIsNotNone(plan.record_failure("g1", "a", self.large, "crash"))

    def test_lanes_are_independent(self):
        plan = FallbackPlan([self.small])
        self.fail_twice(plan, lane="g1")
        self.assertEqual(self.fail_twice(plan, lane="g2")[0], self.small)

    def test_failing_fallback_is_reported_without_reswap(self):
        plan = FallbackPlan([self.small, self.other, self.gemma])
        self.fail_twice(plan)
        for question in ("q", "later"):
            for _ in range(3):
                self.assertIsNone(plan.record_failure("g1", question, self.small, "crash"))
        self.assertEqual(plan.status("g1"), "fallback_failed")

    def test_failed_fallback_launch_consumes_only_swap(self):
        plan = FallbackPlan([self.small, self.other])
        self.fail_twice(plan)
        self.assertIsNone(plan.record_failure("g1", "q", self.large, "model_start"))
        self.assertEqual(plan.status("g1"), "fallback_failed")

    def test_prefer_same_family_over_larger_other_family(self):
        alternative = Model("Llama 3.1 7B", 7000, available=True)
        plan = FallbackPlan([alternative, self.small])
        self.assertEqual(self.fail_twice(plan)[0], self.small)

    def test_explicit_family_controls_selection(self):
        original = Model("Custom model", 8000, family="Acme")
        sibling = Model("Other custom", 1000, family="acme", available=True)
        plan = FallbackPlan([self.small, sibling])
        self.assertEqual(self.fail_twice(plan, original)[0], sibling)

    def test_unknown_families_do_not_automatically_match(self):
        original = Model("Custom", 8000)
        other = Model("Other", 1000, available=True)
        plan = FallbackPlan([self.small, other])
        self.assertEqual(self.fail_twice(plan, original)[0], self.small)

    def test_closest_smaller_file_within_family(self):
        tiny = Model("Qwen3 1.7B", 1700, available=True)
        plan = FallbackPlan([tiny, self.small])
        self.assertEqual(self.fail_twice(plan)[0], self.small)

    def test_gemma_3_1b_is_last_resort(self):
        original = Model("Gemma 3 4B", 4000)
        plan = FallbackPlan([self.gemma, self.other])
        self.assertEqual(self.fail_twice(plan, original)[0], self.other)

    def test_gemma_filename_is_last_resort(self):
        gemma = Model("gemma-3-1b-it-Q4_K_M.gguf", 3000, available=True)
        plan = FallbackPlan([gemma, self.other])
        self.assertEqual(self.fail_twice(plan)[0], self.other)

    def test_gemma_is_used_if_only_eligible_model(self):
        self.assertEqual(self.fail_twice(FallbackPlan([self.gemma]))[0], self.gemma)

    def test_never_swaps_to_equal_or_larger_model(self):
        equal = Model("Qwen different quant", 8000, available=True)
        larger = Model("Qwen bigger", 8001, available=True)
        plan = FallbackPlan([equal, larger])
        self.assertIsNone(self.fail_twice(plan))
        self.assertEqual(plan.status("g1"), "no_fallback")

    def test_byte_counts_not_rounded_megabytes(self):
        original = Model("Qwen source", 1048577)
        smaller = Model("Qwen small", 1048576, available=True)
        self.assertEqual(self.fail_twice(FallbackPlan([smaller]), original)[0], smaller)

    def test_same_name_cannot_swap_to_itself(self):
        duplicate = Model("qwen3 8b", 4000, available=True)
        self.assertIsNone(self.fail_twice(FallbackPlan([duplicate])))

    def test_same_path_cannot_swap_to_itself(self):
        duplicate = Model("Other label", 4000, self.large.path, available=True)
        self.assertIsNone(self.fail_twice(FallbackPlan([duplicate])))

    def test_same_hash_cannot_swap_to_itself(self):
        original = Model("Original", 8000, sha256="a" * 64)
        duplicate = Model("Duplicate", 4000, sha256="a" * 64, available=True)
        self.assertIsNone(self.fail_twice(FallbackPlan([duplicate]), original))

    def test_known_bad_models_are_excluded(self):
        bad = Model("Qwen bad", 5000, known_good=False, available=True)
        self.assertEqual(self.fail_twice(FallbackPlan([bad, self.other]))[0], self.other)

    def test_offline_never_selects_missing_catalog_entry(self):
        missing = Model("Qwen catalog", 6000)
        plan = FallbackPlan([self.other], [missing], offline=True)
        self.assertEqual(self.fail_twice(plan)[0], self.other)

    def test_online_can_select_known_good_pinned_catalog_entry(self):
        missing = Model("Qwen catalog", 6000)
        plan = FallbackPlan([], [missing], offline=False)
        self.assertEqual(self.fail_twice(plan)[0], missing)

    def test_online_still_rejects_unknown_unavailable_local_entry(self):
        missing = Model("Qwen nonexistent", 6000)
        self.assertIsNone(self.fail_twice(FallbackPlan([missing], offline=False)))

    def test_available_catalog_entry_can_be_selected_offline(self):
        self.assertEqual(self.fail_twice(FallbackPlan([], [self.small]))[0], self.small)

    def test_local_file_preferred_over_same_family_download(self):
        missing = Model("Qwen catalog", 6000)
        plan = FallbackPlan([self.small], [missing], offline=False)
        self.assertEqual(self.fail_twice(plan)[0], self.small)

    def test_no_candidate_does_not_consume_swap(self):
        plan = FallbackPlan([])
        self.assertIsNone(self.fail_twice(plan))
        plan.models = (self.small,)
        self.assertEqual(plan.record_failure("g1", "q", self.large, "crash")[0], self.small)

    def test_invalid_model_metadata_is_rejected(self):
        for size in (0, -1, True, 1.2):
            with self.assertRaises(ValueError):
                Model("Model", size)
        with self.assertRaises(ValueError):
            Model(" ", 100)

    def test_invalid_failure_metadata_is_rejected(self):
        plan = FallbackPlan([self.small])
        for lane, question, reason in (("", "q", "crash"), ("g1", None, "crash"), ("g1", "q", "")):
            with self.assertRaises(ValueError):
                plan.record_failure(lane, question, self.large, reason)
        self.assertEqual(plan.failure_count("g1", "q"), 0)

    def test_concurrent_failures_cannot_allocate_multiple_swaps(self):
        plan = FallbackPlan([self.small, self.other])
        offers = []
        barrier = threading.Barrier(8)

        def fail():
            barrier.wait()
            offers.append(plan.record_failure("g1", "q", self.large, "crash"))

        threads = [threading.Thread(target=fail) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(offer is not None for offer in offers), 1)
        self.assertEqual(plan.failure_count("g1", "q"), 8)


if __name__ == "__main__":
    unittest.main()
