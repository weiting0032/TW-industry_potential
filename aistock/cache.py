"""以 parquet 落地的本地快取，避免同一天重複打交易所 API。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import CACHE_DIR


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.parquet"


def load(key: str, ttl_hours: float) -> Optional[pd.DataFrame]:
    """讀取未過期的快取；不存在或過期回傳 None。"""
    p = _path(key)
    if not p.exists():
        return None
    if (time.time() - p.stat().st_mtime) > ttl_hours * 3600:
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        p.unlink(missing_ok=True)
        return None


def save(key: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    try:
        df.to_parquet(_path(key), index=False)
    except Exception:
        pass  # 快取寫入失敗不該中斷主流程


def clear() -> int:
    """清空快取，回傳刪除檔數。"""
    n = 0
    for p in CACHE_DIR.glob("*.parquet"):
        p.unlink(missing_ok=True)
        n += 1
    return n
