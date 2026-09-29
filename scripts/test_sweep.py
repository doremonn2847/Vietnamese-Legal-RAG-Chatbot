import unittest

from sweep import BRANCH_DEPTH_PAIRS, EVIDENCE_CAPS, RERANK_DEPTHS, sweep_configs


class SweepTest(unittest.TestCase):
    def test_required_grid_is_frozen(self):
        self.assertEqual(BRANCH_DEPTH_PAIRS, ((10, 10), (20, 20), (40, 40), (20, 40), (40, 20)))
        self.assertEqual(RERANK_DEPTHS, (10, 20, 40))
        self.assertEqual(EVIDENCE_CAPS, (3, 5, 8))

    def test_sweep_records_requested_and_achieved_depth(self):
        rows = sweep_configs({"bm25": [{"article_id": "a"}], "dense": [{"article_id": "a"}]})
        self.assertEqual(len(rows), 5 * 3 * 3)
        self.assertTrue(all(row["measurement_status"] == "score_only_unmeasured_latency" for row in rows))
        self.assertTrue(all(row["achieved_unique_articles"] == 1 for row in rows))


if __name__ == "__main__":
    unittest.main()
