"""每日快照的落地與讀取。

與 cache.py 的差別：
  cache.py    ── 暫時性、有時效、會被清空、不進版控
  snapshots.py ── 長期保存的歷史紀錄，由排程寫入並 commit 進 repo

快照只存「無法重新推導」的個股市場資料（價、量、本益比、均線），
不存產業歸類 —— 產業字典是 aistock/industry.py 的職責，讀取時才 join。
這樣日後調整 INDUSTRY_MAP，全部歷史快照會自動套用新分類，不必回填。
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from .config import SNAPSHOT_DIR

# 快照保留的欄位：交易所公告值 + 由歷史價算出的技術面
SNAPSHOT_COLUMNS = [
    "code", "name", "market", "close", "change", "open", "high", "low", "volume",
    "pe", "pb", "dividend_yield", "fiscal",
    "prev_close", "high_52w", "low_52w", "ma20", "ma60", "ma120", "hist_bars",
]

_NAME_RE = re.compile(r"^(\d{8})\.parquet$")

# 本益比覆蓋率低於此值即視為「不完整」，排程下一班會重抓覆蓋掉。
# 交易所的本益比 API 公布時間比收盤行情晚，太早跑會產出有價無本益比的空殼快照；
# 光看「檔案存不存在」就略過，該交易日的資料會永久壞在那裡。
MIN_PE_COVERAGE = 0.5


def path_for(date_str: str) -> Path:
    return SNAPSHOT_DIR / f"{date_str}.parquet"


def save(date_str: str, df: pd.DataFrame) -> Path:
    """寫入單日快照，回傳檔案路徑。"""
    cols = [c for c in SNAPSHOT_COLUMNS if c in df.columns]
    out = df[cols].drop_duplicates(subset="code").reset_index(drop=True)
    p = path_for(date_str)
    p.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(p, index=False, compression="zstd")
    return p


def load(date_str: str, columns: Optional[List[str]] = None) -> Optional[pd.DataFrame]:
    p = path_for(date_str)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p, columns=columns)
    except Exception:
        return None


def pe_coverage(df: Optional[pd.DataFrame]) -> float:
    """本益比有正值的比例。無資料回傳 0.0。"""
    if df is None or df.empty or "pe" not in df.columns:
        return 0.0
    pe = pd.to_numeric(df["pe"], errors="coerce")
    return float((pe > 0).sum()) / len(df)


def min_market_pe_coverage(df: Optional[pd.DataFrame]) -> float:
    """上市與上櫃「分別」計算本益比覆蓋率，取較差的一個。

    為什麼不看整體比例：上市與上櫃是兩支獨立的本益比 API，公布時間也不同。
    上櫃尚未公布時，光靠上市那半邊就能讓整體覆蓋率衝到七成以上、
    輕鬆越過門檻被判定為「完整」，上櫃成分股的本益比就永久缺在那一天。
    """
    if df is None or df.empty or "pe" not in df.columns:
        return 0.0
    if "market" not in df.columns:
        return pe_coverage(df)
    per = [pe_coverage(g) for _, g in df.groupby("market") if not g.empty]
    return min(per) if per else 0.0


def is_complete(date_str: str, universe: Optional[Iterable[str]] = None) -> bool:
    """快照是否「已存在、成分股到齊、且上市櫃兩邊本益比覆蓋率都夠」。

    universe 傳入目前的成分股代號集合時，會一併檢查有沒有缺股。
    這是為了處理產業字典擴編：新加的股票在舊快照裡整列都不存在，
    只看本益比覆蓋率的話舊快照會被判定為完整、永遠不補，歷史就永遠缺那幾檔。
    寫檔時每個成分股都必定有一列（沒資料就是整列 NaN），所以「有沒有那一列」
    是精確的判準，不需要再設比例門檻。

    刻意用參數傳入而不 import industry：快照層不該知道產業分類的存在。
    """
    df = load(date_str, columns=["code", "pe", "market"])
    if df is None or df.empty:
        return False
    if universe is not None and set(universe) - set(df["code"].astype(str)):
        return False
    return min_market_pe_coverage(df) >= MIN_PE_COVERAGE


def latest_complete_date(universe: Optional[Iterable[str]] = None,
                         max_scan: int = 10) -> Optional[str]:
    """最近一份「完整」的快照；往回找不到就退回最新的那份。

    給 App 當預設日期用。當日 13:30 收盤到交易所公布本益比之間有好幾個小時空窗，
    這段時間最新快照必然不完整（有價無本益比）。若一律預設顯示最新日期，
    使用者每個交易日下午打開都會看到一片「—」加一條警告 ——
    預設落在最近一份完整資料上，才是他真正想看的東西。
    不完整的那份仍然留在下拉選單裡，想看當日盤後價量隨時可以切過去。
    """
    days = available_dates()
    if not days:
        return None
    for d in reversed(days[-max_scan:]):
        if is_complete(d, universe):
            return d
    return days[-1]


def available_dates() -> List[str]:
    """已存在的快照日期（YYYYMMDD 升冪）。純讀本地檔案，不發網路請求。"""
    if not SNAPSHOT_DIR.exists():
        return []
    out = []
    for p in SNAPSHOT_DIR.iterdir():
        m = _NAME_RE.match(p.name)
        if m:
            out.append(m.group(1))
    return sorted(out)


def pe_history(limit: Optional[int] = None) -> pd.DataFrame:
    """把歷來快照的本益比攤成長表 (date, code, pe)。

    這是「本益比歷史分位」唯一的資料來源，而且是真的歷史本益比：
    交易所的本益比 API 本來就能指定日期查詢，回補時抓到的是各該日實際公告值，
    不是拿今天的 EPS 去回推。用價格比例回推的做法在獲利高速成長的族群會嚴重失真
    （EPS 漲一倍，過去的本益比就會被低估一半），這裡刻意不那樣做。

    只讀 code/pe 兩欄，250 份快照的載入成本因此壓在一秒上下。
    """
    days = available_dates()
    if limit:
        days = days[-limit:]

    frames = []
    for d in days:
        df = load(d, columns=["code", "pe"])
        if df is None or df.empty:
            continue
        df = df.copy()
        df["date"] = d
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["code", "pe", "date"])
    out = pd.concat(frames, ignore_index=True)
    out["code"] = out["code"].astype(str)
    return out


def latest_date() -> Optional[str]:
    days = available_dates()
    return days[-1] if days else None


def nearest_on_or_before(date: dt.date) -> Optional[str]:
    """找出該日（含）之前最近的一份快照。"""
    target = date.strftime("%Y%m%d")
    usable = [d for d in available_dates() if d <= target]
    return usable[-1] if usable else None
