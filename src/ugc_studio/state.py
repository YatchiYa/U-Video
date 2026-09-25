"""Content-addressed asset cache for a project folder.

Every generated asset (keyframe, clip, voice line, overlay...) is stored with the hash of *everything it was
made from*: prompts, seeds, resolution, and the content of input files (so a regenerated upstream image
invalidates exactly the shots that used it). A build only redoes assets whose inputs changed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

_FILE_HASH_CACHE: dict[tuple[str, float, int], str] = {}


def file_hash(path: str | Path) -> str:
    p = Path(path)
    st = p.stat()
    key = (str(p.resolve()), st.st_mtime, st.st_size)
    if key not in _FILE_HASH_CACHE:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _FILE_HASH_CACHE[key] = h.hexdigest()[:20]
    return _FILE_HASH_CACHE[key]


def _normalize(obj: Any) -> Any:
    """Replace file references (dicts {"file": path}) by their content hash, recursively."""
    if isinstance(obj, dict):
        if set(obj) == {"file"}:
            p = obj["file"]
            return {"file_sha": file_hash(p) if p and Path(p).is_file() else None}
        return {k: _normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def inputs_hash(inputs: dict[str, Any]) -> str:
    blob = json.dumps(_normalize(inputs), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def ref(path: str | Path | None) -> dict[str, str | None]:
    """Mark a path as a file input whose *content* participates in the hash."""
    return {"file": str(path) if path else None}


class State:
    def __init__(self, project_dir: str | Path):
        self.dir = Path(project_dir)
        self.path = self.dir / ".ugc" / "state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, Any] = {"assets": {}, "timings": {}}
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text())
                self.data.setdefault("assets", {})
                self.data.setdefault("timings", {})
            except json.JSONDecodeError:
                pass  # corrupt state: rebuild is always safe because assets are re-validated by hash

    # ---------------------------------------------------------------- queries
    def fresh(self, key: str, inputs: dict[str, Any]) -> bool:
        a = self.data["assets"].get(key)
        if not a or a.get("hash") != inputs_hash(inputs):
            return False
        return all((self.dir / p).exists() for p in a.get("paths", []))

    def get(self, key: str) -> dict[str, Any] | None:
        return self.data["assets"].get(key)

    def path_of(self, key: str) -> Path | None:
        a = self.get(key)
        return self.dir / a["paths"][0] if a and a.get("paths") else None

    # ---------------------------------------------------------------- updates
    def commit(self, key: str, inputs: dict[str, Any], paths: list[str | Path], **meta: Any) -> None:
        rel = [str(Path(p).resolve().relative_to(self.dir.resolve())) for p in paths]
        self.data["assets"][key] = {"hash": inputs_hash(inputs), "paths": rel, "time": time.time(), **meta}
        self.save()

    def invalidate(self, prefix: str) -> list[str]:
        gone = [k for k in self.data["assets"] if k == prefix or k.startswith(prefix + ":")]
        for k in gone:
            del self.data["assets"][k]
        self.save()
        return gone

    def record_timing(self, kind: str, seconds: float) -> None:
        t = self.data["timings"].setdefault(kind, [])
        t.append(round(seconds, 1))
        del t[:-10]
        self.save()

    def typical_seconds(self, kind: str, default: float) -> float:
        t = self.data["timings"].get(kind)
        return float(sorted(t)[len(t) // 2]) if t else default

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False))
        os.replace(tmp, self.path)  # atomic: a crash never leaves a half-written state
