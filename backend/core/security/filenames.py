"""Safe filenames and path confinement."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from core.errors import InvalidRequest

_BAD = re.compile(r"[^A-Za-z0-9-]+")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def sanitize_filename(name: str | None, ext: str, fallback: str = "media", max_len: int = 80) -> str:
    """Produce a harmless display filename (used only in Content-Disposition,
    never as a path on disk)."""
    base = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    base = _BAD.sub("_", base).strip("_-")[:max_len].strip("_-")
    if not base or base.lower() in _WINDOWS_RESERVED:
        base = fallback
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)[:8].lower() or "bin"
    return f"{base}.{ext}"


def confine(root: Path, candidate: Path) -> Path:
    """Resolve `candidate` and require it to live inside `root` (no traversal,
    no symlink escape)."""
    root_r = root.resolve()
    cand = candidate.resolve()
    if cand != root_r and root_r not in cand.parents:
        raise InvalidRequest("Path escapes the working directory.")
    return cand
