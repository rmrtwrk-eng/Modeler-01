"""Project files (*.shipstab): human-readable JSON, versioned."""
from __future__ import annotations

import json

from .hull import Hull

FORMAT = "shipstab-project"
VERSION = 1


def save_project(path: str, hull: Hull) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"format": FORMAT, "version": VERSION, "hull": hull.to_dict()}, fh, indent=1)


def load_project(path: str) -> Hull:
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    if d.get("format") != FORMAT:
        raise ValueError("Not a ShipStab project file")
    if d.get("version", 0) > VERSION:
        raise ValueError(f"Project was saved by a newer ShipStab (file version {d['version']}); please update")
    return Hull.from_dict(d["hull"])
