import os
from typing import Dict

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _lower_keys(d: Dict[str, str]) -> Dict[str, str]:
    return {(k or "").strip().lower(): v for k, v in d.items()}


def load_symbol_maps(path: str = os.path.join(BASE_DIR, "symbol_maps.yaml")) -> Dict[str, Dict[str, str]]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: Dict[str, Dict[str, str]] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out[key] = _lower_keys(value)
    return out


_maps = load_symbol_maps()

COMMODITY_MAP: Dict[str, str] = _maps.get("commodity_map", {})
FX_ALIAS: Dict[str, str] = _maps.get("fx_alias", {})
INDEX_MAP: Dict[str, str] = _maps.get("index_map", {})
EQUITY_MAP: Dict[str, str] = _maps.get("equity_map", {})
