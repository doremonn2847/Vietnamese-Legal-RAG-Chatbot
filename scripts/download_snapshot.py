"""Download only the four pinned source files; validate size and SHA-256."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

REVISION = "8977887f17be2defae4c5171d55562e1cde7d695"
DATASET = "th1nhng0/vietnamese-legal-documents"
ROOT = Path(__file__).resolve().parents[1] / "data" / "raw" / REVISION


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(url, destination, size, expected_hash):
    if destination.exists():
        assert destination.stat().st_size == size and sha256(destination) == expected_hash
        return
    temporary = destination.with_suffix(destination.suffix + ".part")
    block = 4 * 1024 * 1024

    def fetch(start):
        end = min(start + block, size) - 1
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(request, timeout=45) as response:
                    assert response.status == 206
                    assert response.headers["Content-Range"] == f"bytes {start}-{end}/{size}"
                    data = response.read()
                assert len(data) == end - start + 1
                return start, data
            except Exception:
                if attempt == 2:
                    raise

    with temporary.open("wb") as stream, concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        completed = 0
        for start, data in pool.map(fetch, range(0, size, block)):
            stream.seek(start)
            stream.write(data)
            completed += len(data)
            if completed // (64 * 1024 * 1024) != (completed - len(data)) // (64 * 1024 * 1024):
                print(f"{destination.name}: {completed}/{size} bytes", flush=True)
    assert temporary.stat().st_size == size and sha256(temporary) == expected_hash
    temporary.rename(destination)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/api/datasets/{DATASET}/tree/{REVISION}?recursive=true"
    with urllib.request.urlopen(url, timeout=30) as response:
        entries = json.load(response)
    (ROOT / "upstream-tree.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    files = []
    for entry in entries:
        path = entry["path"]
        if path not in {"README.md", "data/metadata.parquet", "data/content.parquet", "data/relationships.parquet"}:
            continue
        url = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{path}"
        destination = ROOT / Path(path).name
        digest = entry.get("lfs", {}).get("oid")
        if digest:
            download(url, destination, entry["size"], digest)
        elif not destination.exists():
            with urllib.request.urlopen(url, timeout=30) as response:
                destination.write_bytes(response.read())
        assert destination.stat().st_size == entry["size"]
        files.append({"file": destination.name, "bytes": entry["size"], "sha256": sha256(destination), "url": url})
        print(f"Verified {destination.name}", flush=True)
    (ROOT / "manifest.json").write_text(json.dumps({"dataset": DATASET, "revision": REVISION, "files": files}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
