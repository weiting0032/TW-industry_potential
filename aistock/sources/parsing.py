"""交易所回傳值的共用清洗工具。"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

_TAG = re.compile(r"<[^>]+>")
# 交易所用來表示「無資料 / 不適用」的各種寫法
_NULL_TOKENS = {"", "-", "--", "---", "N/A", "NA", "null", "None", "X"}


def strip_html(v: Any) -> str:
    return _TAG.sub("", str(v)).replace("　", " ").strip()


def to_float(v: Any) -> float:
    """把 '1,130.00' / '-' / '--' / '' 轉成 float，無法解析回 NaN。"""
    s = strip_html(v).replace(",", "").replace("%", "")
    if s in _NULL_TOKENS:
        return math.nan
    try:
        return float(s)
    except ValueError:
        return math.nan


def change_sign(v: Any) -> float:
    """解析證交所 `漲跌(+/-)` 欄位（HTML 包裝）→ +1 / -1 / 0 / NaN。

    `<p> </p>` 代表平盤、`<p>X</p>` 代表無漲跌參考價。
    """
    s = strip_html(v)
    if "+" in s:
        return 1.0
    if "-" in s:
        return -1.0
    if s == "" or s == "\xa0":
        return 0.0
    return math.nan   # 含 X 等特殊註記


def field_index(fields: List[str]) -> Dict[str, int]:
    """欄位名稱 → 索引。交易所欄名常帶全形空白或換行，一律正規化後再對應。"""
    out: Dict[str, int] = {}
    for i, name in enumerate(fields):
        key = strip_html(name).replace(" ", "").replace("\n", "")
        out.setdefault(key, i)
    return out


def pick(row: List[Any], idx: Dict[str, int], *names: str) -> Optional[Any]:
    """依序嘗試多個欄位別名，取第一個存在的值。"""
    for n in names:
        i = idx.get(n)
        if i is not None and i < len(row):
            return row[i]
    return None
