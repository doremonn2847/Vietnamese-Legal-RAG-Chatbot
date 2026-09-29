import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from e5_artifacts import E5ArtifactSpec

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
            spec = E5ArtifactSpec.pinned_small(); spec_manifest = spec.manifest()
            (model / "artifact_manifest.json").write_text(json.dumps({"spec": spec_manifest, "spec_sha256": hashlib.sha256(json.dumps(spec_manifest, ensure_ascii=False, sort_keys=True).encode()).hexdigest(), "files": {"weights.bin": hashlib.sha256(b"fake").hexdigest()}}), encoding="utf-8")
            class Encoder:
                def encode_documents(self, texts): return [[0.0] * 384 for _ in texts]
                def encode_queries(self, texts): return [[1.0] + [0.0] * 383 for _ in texts]
            report = run_benchmark(model, root / "out.json", encoder_factory=lambda _: Encoder(), repeats=2)
            self.assertEqual(report["counts"], {"documents": 1, "queries": 1})
            self.assertTrue((root / "out.json").is_file())

    def test_rejects_bad_spec_files_repeats_and_timed_vectors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); model = root / "model"; model.mkdir(); (model / "weights.bin").write_bytes(b"fake")
            spec = E5ArtifactSpec.pinned_small(); body = {"spec": spec.manifest(), "spec_sha256": hashlib.sha256(json.dumps(spec.manifest(), ensure_ascii=False, sort_keys=True).encode()).hexdigest(), "files": {"weights.bin": hashlib.sha256(b"fake").hexdigest()}}
            manifest = model / "artifact_manifest.json"; manifest.write_text(json.dumps(body), encoding="utf-8")
            for change in ({"files": {}}, {"spec": {}}):
                candidate = {**body, **change}; manifest.write_text(json.dumps(candidate), encoding="utf-8")
                with self.assertRaises(ValueError): run_benchmark(model, root / "x.json", encoder_factory=lambda _: (_ for _ in ()).throw(AssertionError("loaded")))
            manifest.write_text(json.dumps(body), encoding="utf-8")
            class BadEncoder:
                def __init__(self): self.calls = 0
                def encode_documents(self, texts): self.calls += 1; return [[0.0] * (384 if self.calls == 1 else 2) for _ in texts]
                def encode_queries(self, texts): return [[0.0] * 384 for _ in texts]
            for repeats in (0, 21, True):
                with self.assertRaises(ValueError): run_benchmark(model, root / "x.json", encoder_factory=lambda _: BadEncoder(), repeats=repeats)
            with self.assertRaises(ValueError): run_benchmark(model, root / "x.json", encoder_factory=lambda _: BadEncoder(), repeats=1, documents=["d"], queries=("q",))
            self.assertFalse((root / "x.json").exists())


if __name__ == "__main__":
    unittest.main()
