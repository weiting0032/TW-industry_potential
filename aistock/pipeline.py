"""資料流程協調層：交易日解析 → 全市場抓取 → 對應產業 → 併入技術面 → 快取。"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import cache, snapshots
from .config import (DAILY_CACHE_TTL_HOURS, HISTORY_CACHE_TTL_HOURS,
                     MAX_LOOKBACK_DAYS, QUARTER_MA, SNAPSHOT_ONLY)
from .industry import INDUSTRY_MAP, all_stocks, yahoo_symbol
from .sources import history, tpex, twse

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 交易日解析
# --------------------------------------------------------------------------
def resolve_trading_day(start: Optional[dt.date] = None) -> Optional[str]:
    """回傳 start（含）之前最近一個台股交易日，YYYYMMDD。

    先問 FMTQIK 當月的交易日清單（約 0.6 KB）；跨月時往前一個月再問一次。
    不自建台股行事曆，也不必逐日試打大檔的收盤行情 API。
    FMTQIK 失效時退回逐日探測 MI_INDEX。
    """
    day = start or dt.date.today()

    for back in range(2):                      # 當月 + 前一個月，足以涵蓋任何連假
        probe = day if back == 0 else (day.replace(day=1) - dt.timedelta(days=1))
        days = twse.trading_days(probe.year, probe.month)
        usable = [d for d in days if d <= day.strftime("%Y%m%d")]
        if usable:
            return usable[-1]

    return _probe_trading_day(day)


def _probe_trading_day(day: dt.date) -> Optional[str]:
    """備援：逐日打收盤行情 API，第一個有回應的就是交易日。"""
    for _ in range(MAX_LOOKBACK_DAYS):
        if day.weekday() < 5:                  # 先跳過六日，省下無謂請求
            date_str = day.strftime("%Y%m%d")
            df = twse.fetch(date_str)
            if df is not None and not df.empty:
                return date_str
        day -= dt.timedelta(days=1)
    return None


def recent_trading_days(n: int, end: Optional[dt.date] = None) -> List[str]:
    """回傳 end（含，預設今天）之前最近 n 個交易日，YYYYMMDD 升冪。

    逐「月」問 FMTQIK 拿整月交易日清單，而不是逐「日」呼叫 resolve_trading_day ——
    回補一年時前者約 13 次請求，後者要 350 次（每次還帶 3 秒節流），
    差別是 40 秒與 17 分鐘，對交易所的負擔也差一個數量級。
    """
    end = end or dt.date.today()
    cutoff = end.strftime("%Y%m%d")
    out: List[str] = []
    probe = end
    for _ in range(n // 15 + 4):           # 每月約 20 個交易日，多留幾個月的餘裕
        days = [d for d in twse.trading_days(probe.year, probe.month) if d <= cutoff]
        out = days + out
        if len(out) >= n:
            break
        probe = probe.replace(day=1) - dt.timedelta(days=1)
    return sorted(set(out))[-n:]


# --------------------------------------------------------------------------
# 全市場快照
# --------------------------------------------------------------------------
def fetch_market_snapshot(date: Optional[dt.date] = None,
                          force_refresh: bool = False
                          ) -> Tuple[Optional[str], Optional[pd.DataFrame]]:
    """取得指定日（或最近交易日）的上市＋上櫃全市場快照。"""
    date_str = resolve_trading_day(date)
    if date_str is None:
        return None, None

    # 交易日先用小 API 解析出來，才輪到快取判斷 ——
    # 否則「最近交易日」模式每次開 App 都會白抓 4.5 MB 的收盤行情。
    if not force_refresh:
        cached = cache.load(f"market_{date_str}", DAILY_CACHE_TTL_HOURS)
        if cached is not None:
            return date_str, cached

    twse_df = twse.fetch(date_str)
    tpex_df = tpex.fetch(date_str)
    parts = [d for d in (twse_df, tpex_df) if d is not None and not d.empty]
    if not parts:
        return None, None

    market = pd.concat(parts, ignore_index=True)
    market["code"] = market["code"].astype(str).str.strip()
    market = market.drop_duplicates(subset="code", keep="first")

    # 只有兩個交易所都抓到才寫快取。少了一邊仍然回傳（讓上層自己決定要不要用），
    # 但絕不能存起來 —— 存了之後 12 小時內每一次讀取都會拿到「整個上櫃憑空消失」
    # 的資料，而且完全看不出異常：對帳程式會說幾十檔上櫃股全部下市了。
    if twse_df is not None and tpex_df is not None:
        cache.save(f"market_{date_str}", market)
    else:
        missing = "上市" if twse_df is None else "上櫃"
        log.warning("%s %s 資料缺漏，本次不寫入快取", date_str, missing)

    return date_str, market


# --------------------------------------------------------------------------
# 技術面
# --------------------------------------------------------------------------
def fetch_technicals(date_str: str, force_refresh: bool = False) -> pd.DataFrame:
    key = f"tech_{date_str}"
    if not force_refresh:
        cached = cache.load(key, HISTORY_CACHE_TTL_HOURS)
        if cached is not None:
            return cached

    as_of = pd.Timestamp(dt.datetime.strptime(date_str, "%Y%m%d"))
    symbols = [yahoo_symbol(s.code, s.market) for s in all_stocks()]
    tech = history.fetch_technicals(symbols, as_of=as_of)
    cache.save(key, tech)
    return tech


# --------------------------------------------------------------------------
# 組裝：產業字典 × 市場快照 × 技術面
# --------------------------------------------------------------------------
def _universe_frame() -> pd.DataFrame:
    """把產業字典攤平成 (產業 × 個股) 的長表；一檔股票跨產業會有多列。"""
    rows: List[Dict[str, str]] = []
    for industry, members in INDUSTRY_MAP.items():
        for s in members:
            rows.append({
                "industry": industry,
                "code": s.code,
                "map_name": s.name,
                "market": s.market,
                "role": s.role,
                "symbol": yahoo_symbol(s.code, s.market),
            })
    return pd.DataFrame(rows)


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    """即時抓取與讀快照共用的收尾：補名稱、補收盤價、算衍生欄位。"""
    df["name"] = df["name"].fillna(df["map_name"]).replace("", pd.NA).fillna(df["map_name"])
    if "hist_close" in df.columns:
        # 交易所沒給收盤價時（例如當日無成交），退而用歷史資料的收盤價
        df["close"] = df["close"].fillna(df["hist_close"])
    df["change_pct"] = _change_pct(df)
    df["ma_quarter"] = df.get(f"ma{QUARTER_MA}")
    return df


def build_dataset(date: Optional[dt.date] = None,
                  force_refresh: bool = False,
                  with_technicals: bool = True
                  ) -> Tuple[Optional[str], Optional[pd.DataFrame]]:
    """即時向交易所抓取，回傳 (交易日 YYYYMMDD, 產業成分股完整資料表)。"""
    date_str, market = fetch_market_snapshot(date, force_refresh)
    if date_str is None or market is None:
        return None, None

    df = _universe_frame().merge(
        market.drop(columns=["market"], errors="ignore"),
        on="code", how="left", suffixes=("", "_mkt"),
    )

    if with_technicals:
        df = df.merge(fetch_technicals(date_str, force_refresh), on="symbol", how="left")
    else:
        for col in ("ma20", "ma60", "ma120", "high_52w", "low_52w",
                    "hist_close", "prev_close", "hist_bars"):
            df[col] = pd.NA

    return date_str, _finalize(df)


def build_from_snapshot(date: Optional[dt.date] = None
                        ) -> Tuple[Optional[str], Optional[pd.DataFrame]]:
    """只讀 data/snapshots/ 的既有快照，完全不發網路請求。

    產業歸類在此刻才由 INDUSTRY_MAP join 上去，
    所以調整分類後，歷史快照會立刻套用新分類，不需回填。
    """
    date_str = snapshots.nearest_on_or_before(date) if date else snapshots.latest_date()
    if date_str is None:
        return None, None

    per_code = snapshots.load(date_str)
    if per_code is None or per_code.empty:
        return None, None

    df = _universe_frame().merge(
        per_code.drop(columns=["market"], errors="ignore"), on="code", how="left")
    return date_str, _finalize(df)


def load_dataset(date: Optional[dt.date] = None,
                 mode: str = "auto",
                 force_refresh: bool = False
                 ) -> Tuple[Optional[str], Optional[pd.DataFrame], str]:
    """App 的統一入口，回傳 (交易日, 資料表, 實際資料來源)。

    mode:
      "snapshot" 只讀快照，不對外連線（Streamlit Cloud 用）
      "live"     只即時抓取
      "auto"     依 AISEMI_SNAPSHOT_ONLY 決定；即時抓取失敗時退回快照
    """
    if mode == "snapshot" or (mode == "auto" and SNAPSHOT_ONLY):
        day, df = build_from_snapshot(date)
        return day, df, "snapshot"

    if mode == "live":
        day, df = build_dataset(date, force_refresh)
        return day, df, "live"

    day, df = build_dataset(date, force_refresh)
    if df is not None:
        return day, df, "live"

    day, df = build_from_snapshot(date)      # 交易所抓不到時的救生圈
    return day, df, "snapshot"


def store_snapshot(date: Optional[dt.date] = None) -> Tuple[Optional[str], bool]:
    """排程用：即時抓取當日資料並寫入 data/snapshots/。

    回傳 (交易日, 是否真的寫入檔案)。兩者要分開講，因為「抓取成功」與「有寫檔」
    不是同一件事：若該日已有快照，只在新資料的本益比覆蓋率「不比舊的差」時才覆蓋 ——
    補跑班次遇到交易所暫時性異常（例如上櫃 API 斷線）時，
    不會把已經抓好的完整快照洗成半殘。呼叫端必須據此回報，不能一律說「已寫入」。
    """
    date_str, df = build_dataset(date, force_refresh=True)
    if date_str is None or df is None:
        return None, False

    new_cov = snapshots.min_market_pe_coverage(df)
    new_rows = df["code"].nunique()
    old = snapshots.load(date_str)
    old_cov = snapshots.min_market_pe_coverage(old)
    old_rows = 0 if old is None else old["code"].nunique()

    # 成分股變多時不比較覆蓋率：新名單本來就該取代舊名單
    if old_rows >= new_rows and old_cov > new_cov:
        log.warning("%s 既有快照本益比覆蓋率 %.0f%% 優於本次 %.0f%%，保留舊檔",
                    date_str, old_cov * 100, new_cov * 100)
        return date_str, False

    snapshots.save(date_str, df)
    return date_str, True


def _change_pct(df: pd.DataFrame) -> pd.Series:
    """漲跌幅 % = 漲跌 / 昨收 × 100，昨收 = 今收 − 漲跌。

    少數個股當日的 `漲跌(+/-)` 欄位是 "X"（無漲跌參考價，多見於除權息或變更交易），
    解析後為 NaN；此時改用歷史資料的前一日收盤價回推。
    """
    close = pd.to_numeric(df.get("close"), errors="coerce")
    change = pd.to_numeric(df.get("change"), errors="coerce")
    prev = close - change

    if "prev_close" in df.columns:
        prev = prev.fillna(pd.to_numeric(df["prev_close"], errors="coerce"))

    return ((close - prev) / prev * 100).where(prev > 0)
