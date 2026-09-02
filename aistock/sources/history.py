"""透過 yfinance 取得歷史股價，計算均線與 52 週高低點。

為什麼另外抓歷史：證交所／櫃買的每日 API 只有當天快照，
要算季線必須有連續 60 個交易日的收盤價。

關於股價還原（實測結果，會影響均線正確性）：
  auto_adjust=False 時，Yahoo 的 Close 已針對「除權配股／分割」做過還原，
  但不對「現金股利」還原。實測 2025-09-01：
    2330 / 3661 / 3324（僅配息）→ 與交易所收盤價完全相同
    3163 波若威（有配股）      → 交易所 240.00 vs yfinance 204.26（差 1.175 倍）
  這正是算均線需要的行為：配股造成的價格斷層被抹平，避免季線被除權跳空扭曲；
  同時最新一根 K 棒的價格與交易所公告收盤價一致，兩者可以直接比較。
  若改用 auto_adjust=True 會連現金股利一起還原，反而對不上交易所收盤價。

關於「下載一次、切多個日期」：
  回補歷史快照時，同一批股票會被要求 250 個不同的 as_of 日期。
  若每個日期各下載一次，就是 250 次全批下載 —— 又慢又容易被 Yahoo 限流中斷。
  改成同一個 process 內把收盤價寬表記憶起來，之後每個 as_of 只是切片再算一次均線。
  這也是 HISTORY_PERIOD 取 3 年而非 1 年的原因：最舊的回補日期往前仍要有
  250 個交易日才算得出 52 週高低點，1 年的區間在回補時會整片變成 NaN。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from ..config import HISTORY_PERIOD, MA_WINDOWS

log = logging.getLogger(__name__)

# (symbols, period) -> 收盤價寬表（index=日期, columns=symbol）
_MEMO: Dict[Tuple[Tuple[str, ...], str], pd.DataFrame] = {}


def _extract_close(raw: pd.DataFrame, symbol: str, single: bool) -> Optional[pd.Series]:
    """從 yfinance 的（可能是 MultiIndex 的）結果取出單一標的收盤價。"""
    try:
        if single:
            s = raw["Close"]
        elif isinstance(raw.columns, pd.MultiIndex):
            if symbol in raw.columns.get_level_values(0):
                s = raw[symbol]["Close"]
            elif symbol in raw.columns.get_level_values(1):
                s = raw["Close"][symbol]
            else:
                return None
        else:
            s = raw["Close"]
        if isinstance(s, pd.DataFrame):      # 極少數情況會回 DataFrame
            s = s.iloc[:, 0]
        return s.dropna()
    except (KeyError, IndexError):
        return None


def close_history(symbols: Sequence[str], period: str = HISTORY_PERIOD,
                  chunk_size: int = 40) -> pd.DataFrame:
    """批次下載收盤價，回傳寬表（index=日期, columns=symbol）。

    同一個 process 內同樣的 (symbols, period) 只會真正下載一次。
    """
    import yfinance as yf   # 延後匯入：yfinance 啟動慢，未用到時不付這個成本

    symbols = list(symbols)
    key = (tuple(symbols), period)
    if key in _MEMO:
        return _MEMO[key]

    series: Dict[str, pd.Series] = {}
    for i in range(0, len(symbols), chunk_size):
        batch = symbols[i:i + chunk_size]
        try:
            raw = yf.download(batch, period=period, auto_adjust=False,
                              progress=False, group_by="ticker", threads=True)
        except Exception as exc:
            log.warning("yfinance 批次下載失敗 %s：%s", batch[:3], exc)
            continue
        if raw is None or raw.empty:
            continue

        single = len(batch) == 1
        for sym in batch:
            close = _extract_close(raw, sym, single)
            if close is not None and not close.empty:
                series[sym] = close

    wide = pd.DataFrame(series).sort_index() if series else pd.DataFrame()
    _MEMO[key] = wide
    log.info("yfinance 收盤價寬表：%d 檔 × %d 個交易日", wide.shape[1], wide.shape[0])
    return wide


def technicals_from_history(wide: pd.DataFrame,
                            as_of: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """由收盤價寬表算出各標的的均線與 52 週高低點。

    as_of 有值時只採用該日（含）以前的資料，讓均線與所選交易日對齊。
    回傳欄位：symbol, ma20, ma60, ma120, hist_close, prev_close,
              high_52w, low_52w, hist_bars
    """
    cols = ["symbol", "hist_close", "prev_close", "hist_bars", "high_52w", "low_52w"] + \
           [f"ma{w}" for w in MA_WINDOWS]
    if wide is None or wide.empty:
        return pd.DataFrame(columns=cols)

    frame = wide if as_of is None else wide.loc[wide.index <= as_of]
    rows: List[Dict[str, object]] = []
    for sym in frame.columns:
        close = frame[sym].dropna()
        if close.empty:
            continue
        rec: Dict[str, object] = {
            "symbol": sym,
            "hist_close": float(close.iloc[-1]),
            # 前一交易日收盤，用於交易所漲跌欄位缺漏時回推漲跌幅
            "prev_close": float(close.iloc[-2]) if len(close) >= 2 else float("nan"),
            "hist_bars": int(len(close)),
            "high_52w": float(close.tail(250).max()),
            "low_52w": float(close.tail(250).min()),
        }
        for w in MA_WINDOWS:
            # 資料不足 w 根就給 NaN，不要用不完整的均線誤導判斷
            rec[f"ma{w}"] = float(close.rolling(w).mean().iloc[-1]) if len(close) >= w else float("nan")
        rows.append(rec)

    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def fetch_technicals(symbols: Sequence[str],
                     as_of: Optional[pd.Timestamp] = None,
                     chunk_size: int = 40) -> pd.DataFrame:
    """下載歷史價並算出指定日的技術面欄位（下載結果在 process 內共用）。"""
    return technicals_from_history(close_history(symbols, chunk_size=chunk_size), as_of)
