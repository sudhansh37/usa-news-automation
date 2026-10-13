"""Config loader - config.yaml + environment variables.

Sab kuch config.yaml se aata hai; secrets/keys env (ya GitHub secrets) se.
"""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    """config.yaml load karo (default repo root me). Dict return karta hai."""
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = str(ROOT)
    return cfg


def env(*names, default=None):
    """Pehla available env var return karo (None-safe)."""
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default
