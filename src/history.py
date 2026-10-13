"""Seen-news history - duplicate videos na banein."""
import json
from pathlib import Path


def _path(cfg):
    return Path(cfg["_root"]) / "data" / "seen.json"


def load(cfg):
    p = _path(cfg)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {"links": [], "titles": []}
    return {"links": [], "titles": []}


def save(cfg, data):
    p = _path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def is_seen(data, item):
    link = item.get("link", "")
    title = item.get("title", "").lower()
    if link and link in data.get("links", []):
        return True
    return title in data.get("titles", [])


def add(cfg, data, item):
    if item.get("link"):
        data.setdefault("links", []).append(item["link"])
    data.setdefault("titles", []).append(item.get("title", "").lower())
    # history ko bounded rakho
    data["links"] = data["links"][-500:]
    data["titles"] = data["titles"][-500:]
    save(cfg, data)
