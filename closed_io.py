#!/usr/bin/env python3
"""closed_io.py - safe reader for strategy/_closed.json.

Defense-in-depth from s93-F2 incident: file must be dict, list is normalized.
"""
import json
import sys
from pathlib import Path


def load_closed_normalized(path):
    """Dict -> (data, False). List -> (normalized_dict, True)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw, False
    if isinstance(raw, list):
        norm = {
            "version": 0,
            "updated_session": 0,
            "closed_gaps": [{"id": str(x), "keywords": []} for x in raw],
            "do_not_propose": [],
            "_normalized_from_list": True,
        }
        print("[closed_io] WARN: normalized list->dict from " + str(path), file=sys.stderr)
        return norm, True
    raise ValueError("_closed.json must be dict or list, got " + type(raw).__name__)
