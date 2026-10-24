"""Private Vercel Blob storage for real-cabinet presets (drawing set + photos that must not be in the public repo).

The engine reads its own private Blob store with the ``BLOB_READ_WRITE_TOKEN`` Vercel injects when the store is
connected to the project; nothing here is ever served from a public Blob URL. Standard library only (urllib), the same
REST protocol as Vercel's official SDK (``vercel-blob``): ``PUT|GET https://vercel.com/api/blob`` with
``x-api-version: 12``, private blobs downloaded from their store URL with the same bearer token.

    EAGLE_PRESET_BLOB=presets/emerson/   prefix of the preset in the store (unset: no hosted preset)
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = os.environ.get("VERCEL_BLOB_API_URL") or "https://vercel.com/api/blob"
SYNC_EVERY = 600          # seconds between re-listing the store (a new upload shows up within this time)
_lock = threading.Lock()
_synced = {}


def token():
    return (os.environ.get("BLOB_READ_WRITE_TOKEN") or os.environ.get("VERCEL_BLOB_READ_WRITE_TOKEN") or "").strip()


def enabled():
    return bool(token())


def _call(method, url, data=None, headers=None, timeout=60, api=True):
    h = {"authorization": f"Bearer {token()}"}
    if api:
        h["x-api-version"] = "12"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def put(pathname, data, content_type="application/octet-stream"):
    """Store bytes privately at ``pathname`` (overwrites); returns the blob record."""
    url = f"{API}?{urllib.parse.urlencode({'pathname': pathname})}"
    return json.loads(_call("PUT", url, data, {"x-vercel-blob-access": "private", "x-allow-overwrite": "1",
                                               "x-add-random-suffix": "0", "x-content-type": content_type}))


def list_blobs(prefix):
    out, cursor = [], None
    while True:
        params = {"prefix": prefix, "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        page = json.loads(_call("GET", f"{API}?{urllib.parse.urlencode(params)}"))
        out += page.get("blobs") or []
        cursor = page.get("cursor")
        if not page.get("hasMore") or not cursor:
            return out


def sync(prefix, dst, force=False):
    """Mirror the blobs under ``prefix`` into ``dst`` (download what is missing or changed in size); returns ``dst``.

    Listing is throttled to once per SYNC_EVERY seconds per prefix; files land atomically."""
    dst = Path(dst)
    with _lock:
        if not force and time.time() - _synced.get(prefix, 0) < SYNC_EVERY and dst.is_dir():
            return dst
        dst.mkdir(parents=True, exist_ok=True)
        for b in list_blobs(prefix):
            name = b["pathname"][len(prefix):]
            if not name or "/" in name or name.startswith("."):
                continue
            target = dst / name
            if target.exists() and target.stat().st_size == int(b.get("size") or -1):
                continue
            data = _call("GET", b.get("downloadUrl") or b["url"], timeout=120, api=False)
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, target)
        _synced[prefix] = time.time()
    return dst
