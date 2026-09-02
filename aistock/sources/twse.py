"""上市（TWSE）每日資料。

兩支官方 API：
  1. MI_INDEX  ── 每日收盤行情(全部)：收盤價、漲跌、成交量、本益比
  2. BWIBBU_d  ── 個股日本益比、殖利率及股價淨值比：本益比、殖利率、股價淨值比、財報年季

以 BWIBBU_d 的本益比為準（欄位語意最明確），MI_INDEX 補價量。

重要：BWIBBU_d 的公布時間比收盤行情晚（實測台北時間 15:08 仍回「沒有符合條件的資料」），
而 MI_INDEX 的「每日收盤行情(全部)」本身就帶一欄本益比、收盤後即可取得。
因此收盤行情的本益比一併解析下來，在 BWIBBU_d 尚未公布時充當備援，
避免排程在下午跑出「有價無本益比」的空殼快照。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .http import get_json
from .parsing import change_sign, field_index, pick, strip_html, to_float

_HOST = "twse"
_MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
_BWIBBU = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"


def _quotes(date_str: str) -> Optional[pd.DataFrame]:
    """date_str: YYYYMMDD"""
    payload = get_json(_MI_INDEX, {"date": date_str, "type": "ALL", "response": "json"},
                       host_key=_HOST)
    if not isinstance(payload, dict):
        return None

    for table in payload.get("tables", []):
        fields = table.get("fields") or []
        idx = field_index(fields)
        if "證券代號" not in idx or "收盤價" not in idx:
            continue

        rows = []
        for r in table.get("data", []):
            close = to_float(pick(r, idx, "收盤價"))
            diff = to_float(pick(r, idx, "漲跌價差"))
            sign = change_sign(pick(r, idx, "漲跌(+/-)"))
            change = sign * diff if pd.notna(sign) and pd.notna(diff) else float("nan")
            rows.append({
                "code": strip_html(pick(r, idx, "證券代號")),
                "name": strip_html(pick(r, idx, "證券名稱")),
                "close": close,
                "change": change,
                "open": to_float(pick(r, idx, "開盤價")),
                "high": to_float(pick(r, idx, "最高價")),
                "low": to_float(pick(r, idx, "最低價")),
                "volume": to_float(pick(r, idx, "成交股數")),
                # 收盤行情自帶的本益比：BWIBBU_d 尚未公布時的備援來源
                "pe_quote": to_float(pick(r, idx, "本益比")),
            })
        if rows:
            return pd.DataFrame(rows)
    return None


def _valuation(date_str: str) -> Optional[pd.DataFrame]:
    payload = get_json(_BWIBBU, {"date": date_str, "selectType": "ALL", "response": "json"},
                       host_key=_HOST)
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return None

    idx = field_index(payload.get("fields") or [])
    rows = []
    for r in payload.get("data", []):
        rows.append({
            "code": strip_html(pick(r, idx, "證券代號")),
            "pe": to_float(pick(r, idx, "本益比")),
            "pb": to_float(pick(r, idx, "股價淨值比")),
            "dividend_yield": to_float(pick(r, idx, "殖利率(%)")),
            "fiscal": strip_html(pick(r, idx, "財報年/季") or ""),
        })
    return pd.DataFrame(rows) if rows else None


def fetch(date_str: str) -> Optional[pd.DataFrame]:
    """抓取單一交易日的上市全市場快照。無資料（休市）回傳 None。"""
    q = _quotes(date_str)
    if q is None or q.empty:
        return None

    v = _valuation(date_str)
    df = q.merge(v, on="code", how="left") if v is not None else q.assign(
        pe=float("nan"), pb=float("nan"), dividend_yield=float("nan"), fiscal="")

    # BWIBBU_d 缺漏（尚未公布或該檔無資料）時，改用收盤行情自帶的本益比
    if "pe_quote" in df.columns:
        df["pe"] = pd.to_numeric(df["pe"], errors="coerce").fillna(
            pd.to_numeric(df["pe_quote"], errors="coerce"))
        df = df.drop(columns=["pe_quote"])

    df["market"] = "TWSE"
    return df


_FMTQIK = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"


def trading_days(year: int, month: int) -> list[str]:
    """回傳該月已發生的交易日（YYYYMMDD 升冪）。

    FMTQIK（每日市場成交資訊）只有約 0.6 KB，卻能一次列出整月交易日；
    用它判斷「哪天有開盤」，比逐日試打 4.5 MB 的 MI_INDEX 便宜好幾個數量級。
    當月只會回到今天為止，過去月份則回整月。
    """
    payload = get_json(_FMTQIK, {"date": f"{year:04d}{month:02d}01", "response": "json"},
                       host_key=_HOST)
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return []

    out = []
    for row in payload.get("data", []):
        try:
            roc_y, m, d = str(row[0]).split("/")
            out.append(f"{int(roc_y) + 1911:04d}{int(m):02d}{int(d):02d}")
        except (ValueError, IndexError):
            continue
    return sorted(out)
