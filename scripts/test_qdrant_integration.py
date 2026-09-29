import os
import unittest
import uuid
from datetime import date

from qdrant_contract import QdrantLocalConfig, QdrantRestAdapter, legal_filter, stable_point_id


@unittest.skipUnless(os.getenv("RUN_QDRANT_INTEGRATION") == "1", "set RUN_QDRANT_INTEGRATION=1 for live local Qdrant")
class QdrantIntegrationTest(unittest.TestCase):
    def test_synthetic_import_filter_and_alias(self):
        api = QdrantRestAdapter(QdrantLocalConfig(api_key=os.environ["QDRANT_API_KEY"]))
        suffix = uuid.uuid4().hex[:8]
        collection = "synthetic_integration_" + suffix
        collection_v2 = collection + "_v2"
        alias = "synthetic_active_" + suffix
        try:
            api.create_collection(collection, 3)
            api.create_collection(collection_v2, 3)
            day = date(2024, 1, 1).toordinal()
            payloads = [
                {"pham_vi": "Trung ương", "provision": "probation", "effective_from_day": day - 100, "effective_to_day": day + 100, "reviewed_status": "reviewed", "central_eligible": True, "reviewed_through_day": day + 10, "child_id": "c1"},
                {"pham_vi": "Địa phương", "provision": "probation", "effective_from_day": day - 100, "effective_to_day": day + 100, "reviewed_status": "reviewed", "central_eligible": False, "reviewed_through_day": day + 10, "child_id": "local"},
                {"pham_vi": "Trung ương", "provision": "probation", "effective_from_day": day + 1, "effective_to_day": day + 100, "reviewed_status": "reviewed", "central_eligible": True, "reviewed_through_day": day + 10, "child_id": "future"},
                {"pham_vi": "Trung ương", "provision": "probation", "effective_from_day": day - 100, "effective_to_day": day, "reviewed_status": "reviewed", "central_eligible": True, "reviewed_through_day": day + 10, "child_id": "expired"},
                {"pham_vi": "Trung ương", "provision": "probation", "effective_from_day": day - 100, "effective_to_day": day + 100, "reviewed_status": "unreviewed", "central_eligible": True, "reviewed_through_day": day + 10, "child_id": "unreviewed"},
                {"pham_vi": "Trung ương", "provision": "probation", "effective_from_day": day - 100, "effective_to_day": day + 100, "reviewed_status": "reviewed", "central_eligible": True, "reviewed_through_day": day - 1, "child_id": "insufficient_review"},
                {"pham_vi": "Trung ương", "provision": "probation", "effective_from_day": day - 100, "effective_to_day": day + 100, "reviewed_status": "reviewed", "central_eligible": True, "reviewed_through_day": day + 100, "child_id": "later_reviewed"},
                {"pham_vi": "Trung ương", "provision": "probation", "effective_from_day": day - 100, "effective_to_day": None, "reviewed_status": "reviewed", "central_eligible": True, "reviewed_through_day": day + 100, "child_id": "reviewed_open"},
                {"pham_vi": "Trung ương", "provision": "probation", "effective_from_day": day - 100, "effective_to_day": None, "reviewed_status": "reviewed", "central_eligible": True, "reviewed_through_day": day + 100, "child_id": "unknown_open"},
            ]
            for payload in payloads:
                payload["reviewed_open_ended"] = False
            payloads[-2]["reviewed_open_ended"] = True
            points = [{"id": stable_point_id("article", "version", p["child_id"]), "vector": [1.0, 0.0, 0.0], "payload": p} for p in payloads]
            with self.assertRaises(ValueError):
                api.upsert(collection, [{"id": "contradictory-open-ended", "vector": [1.0, 0.0, 0.0], "payload": {**payloads[0], "reviewed_open_ended": True}}])
            api.upsert(collection, points)
            api.transport("PUT", f"/collections/{collection}/points?wait=true", {"points": [{"id": stable_point_id("article", "version", "contradictory_preexisting"), "vector": [1.0, 0.0, 0.0], "payload": {**payloads[0], "effective_to_day": day, "reviewed_open_ended": True, "child_id": "contradictory_preexisting"}}]})
            api.transport("PUT", f"/collections/{collection}/points?wait=true", {"points": [{"id": stable_point_id("article", "version", "contradictory_future"), "vector": [1.0, 0.0, 0.0], "payload": {**payloads[0], "effective_to_day": day + 100, "reviewed_open_ended": True, "child_id": "contradictory_future"}}]})
            api.upsert(collection, points)
            v2_points = [{**point, "payload": {**point["payload"], "child_id": "v2-only"}} for point in points]
            api.upsert(collection_v2, v2_points)
            fresh = QdrantRestAdapter(QdrantLocalConfig(api_key=os.environ["QDRANT_API_KEY"]))
            result = fresh.search(collection, [1.0, 0.0, 0.0], legal_filter(legal_date="2024-01-01", provision="probation"), limit=10)
            self.assertEqual({point["payload"]["child_id"] for point in result["result"]}, {"c1", "later_reviewed"})
            open_result = fresh.search(collection, [1.0, 0.0, 0.0], legal_filter(legal_date="2024-01-01", provision="probation", include_open_ended=True), limit=20)
            self.assertIn("reviewed_open", {point["payload"]["child_id"] for point in open_result["result"]})
            self.assertNotIn("unknown_open", {point["payload"]["child_id"] for point in open_result["result"]})
            self.assertNotIn("contradictory_preexisting", {point["payload"]["child_id"] for point in open_result["result"]})
            self.assertNotIn("contradictory_future", {point["payload"]["child_id"] for point in open_result["result"]})
            api.activate_alias(alias, collection)
            api.activate_alias(alias, collection_v2, previous_collection=collection)
            v2_alias_result = fresh.search(alias, [1.0, 0.0, 0.0], legal_filter(legal_date="2024-01-01", provision="probation"), limit=10)
            self.assertEqual({point["payload"]["child_id"] for point in v2_alias_result["result"]}, {"v2-only"})
            api.rollback_alias(alias, collection)
            alias_result = fresh.search(alias, [1.0, 0.0, 0.0], legal_filter(legal_date="2024-01-01", provision="probation"), limit=10)
            self.assertEqual({point["payload"]["child_id"] for point in alias_result["result"]}, {"c1", "later_reviewed"})
        finally:
            for cleanup in (lambda: api.delete_alias(alias), lambda: api.delete_collection(collection), lambda: api.delete_collection(collection_v2)):
                try:
                    cleanup()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
