import unittest

from vaultcheck.collect import bisect_first
from vaultcheck.rpc import ViewError


class BisectWithSkippedHeights(unittest.TestCase):
    def run_case(self, flip: int, missing: set, lo: int = 0, hi: int = 1000) -> int:
        calls = []

        def probe(h):
            calls.append(h)
            if h in missing:
                raise ViewError("UNKNOWN_BLOCK", str(h))
            return h >= flip

        return bisect_first(probe, lambda v: v, lo, hi)

    def test_no_gaps(self):
        self.assertEqual(self.run_case(377, set()), 377)

    def test_skipped_midpoint_does_not_jump_past_flip(self):
        # 500 is the first midpoint; if it is missing the search must not assume 'false' there.
        self.assertEqual(self.run_case(377, {500, 250, 375, 376}), 377)

    def test_flip_right_after_a_gap(self):
        missing = set(range(300, 377))
        self.assertEqual(self.run_case(377, missing), 377)

    def test_flip_on_first_existing_block_after_lo(self):
        self.assertEqual(self.run_case(1, set()), 1)


if __name__ == "__main__":
    unittest.main()
