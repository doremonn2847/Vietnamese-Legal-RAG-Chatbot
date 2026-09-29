import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from cpu_benchmark import run_benchmark


class CpuBenchmarkTest(unittest.TestCase):
    def test_requires_verified_local_manifest_before_loading_and_writes_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model"
            model.mkdir()
            (model / "weights.bin").write_bytes(b"fake")
            calls = []
            with self.assertRaises(ValueError):
                run_benchmark(model, root / "out.json", encoder_factory=lambda _: calls.append(True))
            self.assertEqual(calls, [])
            (model / "artifact_manifest.json").write_text(json.dumps({"model_revision": "a" * 40, "tokenizer_revision": "a" * 40, "recipe": {"document_prefix": "passage: ", "query_prefix": "query: "}, "files": {"weights.bin": hashlib.sha256(b"fake").hexdigest()}}), encoding="utf-8")
            class Encoder:
                def encode_documents(self, texts): return [[0.0, 1.0] for _ in texts]
                def encode_queries(self, texts): return [[1.0, 0.0] for _ in texts]
            report = run_benchmark(model, root / "out.json", encoder_factory=lambda _: Encoder(), repeats=2)
            self.assertEqual(report["counts"], {"documents": 1, "queries": 1})
            self.assertTrue((root / "out.json").is_file())


if __name__ == "__main__":
    unittest.main()
