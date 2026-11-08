"""sha256 manifest for data/, so a reviewer can see the committed snapshots were not edited."""

from __future__ import annotations

import hashlib
import os

NAME = "MANIFEST.sha256"


def _files(data: str) -> list[str]:
    out = []
    for root, _, files in os.walk(data):
        for f in files:
            if f == NAME or f.endswith(".tmp"):
                continue
            out.append(os.path.relpath(os.path.join(root, f), data))
    return sorted(out)


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write(data: str) -> int:
    lines = [f"{_sha(os.path.join(data, rel))}  {rel}" for rel in _files(data)]
    with open(os.path.join(data, NAME), "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(lines)


def verify(data: str) -> list[str]:
    """Return a list of problems (empty = every file matches the manifest)."""
    path = os.path.join(data, NAME)
    if not os.path.exists(path):
        return [f"{NAME} missing"]
    expected = {}
    with open(path) as f:
        for line in f:
            if line.strip():
                digest, rel = line.rstrip("\n").split("  ", 1)
                expected[rel] = digest
    problems = []
    present = set(_files(data))
    for rel, digest in expected.items():
        if rel not in present:
            problems.append(f"missing: {rel}")
        elif _sha(os.path.join(data, rel)) != digest:
            problems.append(f"changed: {rel}")
    for rel in sorted(present - set(expected)):
        problems.append(f"not in manifest: {rel}")
    return problems
