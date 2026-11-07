"""Shared helpers: download a file once and record where it came from.

Every source lands in data/raw/<source_id>/ next to a manifest.json with the
URL, byte count, sha256 and fetch time. Downloads are skipped when the file
already exists unless REFRESH=1 is set, so `make` rebuilds from the saved raw
files and `make refresh` pulls everything again.
"""
import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
UA = "tulsa-pantry-gap/0.1 (personal public-data research project)"
REFRESH = os.environ.get("REFRESH") == "1"


def _record(source_id, name, url, body, extra=None):
    out = RAW / source_id
    mf = out / "manifest.json"
    entry = {
        "file": name, "url": url, "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **(extra or {}),
    }
    items = [e for e in (json.loads(mf.read_text()) if mf.exists() else []) if e["file"] != name]
    mf.write_text(json.dumps(items + [entry], indent=2))


def have(source_id, name):
    return (RAW / source_id / name).exists() and not REFRESH


def get(url, headers=None, timeout=120, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # network hiccup: retry with backoff, then fail loudly
            if i == tries - 1:
                raise RuntimeError(f"download failed: {url}: {e}") from e
            time.sleep(2 * (i + 1))


def download(source_id, name, url, headers=None, extra=None):
    """Save url to data/raw/<source_id>/<name> (unless cached) and log it in the manifest."""
    path = RAW / source_id / name
    if have(source_id, name):
        print(f"{source_id}/{name}: cached")
        return path.read_bytes()
    body = get(url, headers=headers)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    _record(source_id, name, url, body, extra)
    print(f"{source_id}/{name}: {len(body):,} bytes")
    return body


def save(source_id, name, url, body, extra=None):
    """Save bytes assembled during fetching (a filtered subset, merged pages) with provenance."""
    path = RAW / source_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    _record(source_id, name, url, body, extra)
    print(f"{source_id}/{name}: {len(body):,} bytes")
