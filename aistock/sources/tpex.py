"""上櫃（TPEx）每日資料。

主要 API（可指定日期）：
  1. afterTrading/otc        ── 上櫃股票每日收盤行情
  2. afterTrading/peQryDate  ── 上櫃股票本益比、殖利率、股價淨值比

備援 API（只有「最近一個交易日」，櫃買改版時當救生圈）：
  openapi/v1/tpex_mainboard_daily_close_quotes
  openapi/v1/tpex_mainboard_peratio_analysis
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .http import get_json
from .parsing import field_index, pick, strip_html, to_float

_HOST = "tpex"
_OTC = "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
_PE = "https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate"
_OPENAPI_QUOTE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
_OPENAPI_PE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"


def _roc_date(date_str: str) -> str:
    """YYYYMMDD → YYYY/MM/DD（櫃買新版 www API 收西元年）。"""
    return f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:8]}"


def _first_table(payload) -> Optional[dict]:
    if not isinstance(payload, dict):
        return None
    for t in payload.get("tables", []):
        if t.get("data"):
            return t
    return None


def _quotes(date_str: str) -> Optional[pd.DataFrame]:
    payload = get_json(_OTC, {"date": _roc_date(date_str), "type": "EW",
                              "id": "", "response": "json"}, host_key=_HOST)
    table = _first_table(payload)
    if table is None:
        return None

    idx = field_index(table.get("fields") or [])
    rows = []
    for r in table["data"]:
        rows.append({
            "code": strip_html(pick(r, idx, "代號", "股票代號")),
            "name": strip_html(pick(r, idx, "名稱", "公司名稱")),
            "close": to_float(pick(r, idx, "收盤", "收盤價")),
            "change": to_float(pick(r, idx, "漲跌", "漲跌價差")),   # 櫃買本身就帶正負號
            "open": to_float(pick(r, idx, "開盤", "開盤價")),
            "high": to_float(pick(r, idx, "最高", "最高價")),
            "low": to_float(pick(r, idx, "最低", "最低價")),
            "volume": to_float(pick(r, idx, "成交股數")),
        })
    return pd.DataFrame(rows) if rows else None


def _valuation(date_str: str) -> Optional[pd.DataFrame]:
    payload = get_json(_PE, {"date": _roc_date(date_str), "code": "",
                             "response": "json"}, host_key=_HOST)
    table = _first_table(payload)
    if table is None:
        return None

    idx = field_index(table.get("fields") or [])
    rows = []
    for r in table["data"]:
        rows.append({
            "code": strip_html(pick(r, idx, "股票代號", "代號")),
            "pe": to_float(pick(r, idx, "本益比")),
            "pb": to_float(pick(r, idx, "股價淨值比")),
            "dividend_yield": to_float(pick(r, idx, "殖利率(%)")),
            "fiscal": strip_html(pick(r, idx, "財報年/季") or ""),
        })
    return pd.DataFrame(rows) if rows else None


def _openapi_fallback() -> Optional[pd.DataFrame]:
    """櫃買 OpenAPI 只提供最近交易日，僅在主要 API 失效時使用。"""
    q = get_json(_OPENAPI_QUOTE, {}, host_key=_HOST)
    if not isinstance(q, list) or not q:
        return None
    qdf = pd.DataFrame([{
        "code": str(x.get("SecuritiesCompanyCode", "")).strip(),
        "name": str(x.get("CompanyName", "")).strip(),
        "close": to_float(x.get("Close")),
        "change": to_float(x.get("Change")),
        "open": to_float(x.get("Open")),
        "high": to_float(x.get("High")),
        "low": to_float(x.get("Low")),
        "volume": to_float(x.get("TradingShares")),
    } for x in q])

    p = get_json(_OPENAPI_PE, {}, host_key=_HOST)
    if isinstance(p, list) and p:
        pdf = pd.DataFrame([{
            "code": str(x.get("SecuritiesCompanyCode", "")).strip(),
            "pe": to_float(x.get("PriceEarningRatio")),
            "pb": to_float(x.get("PriceBookRatio")),
            "dividend_yield": to_float(x.get("YieldRatio")),
            "fiscal": "",
        } for x in p])
        qdf = qdf.merge(pdf, on="code", how="left")
    else:
        qdf = qdf.assign(pe=float("nan"), pb=float("nan"),
                         dividend_yield=float("nan"), fiscal="")
    return qdf


def fetch(date_str: str) -> Optional[pd.DataFrame]:
    """抓取單一交易日的上櫃全市場快照。無資料（休市）回傳 None。"""
    q = _quotes(date_str)
    if q is None or q.empty:
        df = _openapi_fallback()
        if df is None or df.empty:
            return None
    else:
        v = _valuation(date_str)
        df = q.merge(v, on="code", how="left") if v is not None else q.assign(
            pe=float("nan"), pb=float("nan"), dividend_yield=float("nan"), fiscal="")

    df["market"] = "TPEx"
    return df
