"""本益比分級、產業基準、低基期篩選。"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

PE_NORMAL = "正常"
PE_UNPROFITABLE = "未獲利／負值"

# 交易所公告的本益比若大到失真（多半是獲利趨近於零），視為離群值不納入產業基準
PE_OUTLIER_CAP = 300.0


# --------------------------------------------------------------------------
# 本益比分級
# --------------------------------------------------------------------------
def classify_pe(df: pd.DataFrame) -> pd.DataFrame:
    """標記本益比狀態，並產生排序鍵。

    交易所對虧損公司的表示法不統一：上市用 "-"（解析後為 NaN），
    上櫃可能是 0 或空白。三種情況一律歸為「未獲利／負值」。

    pe_sort 讓「未獲利」在升冪排序時自然落到最後，不需另外拼接 DataFrame。
    """
    out = df.copy()
    pe = pd.to_numeric(out.get("pe"), errors="coerce")

    valid = pe.notna() & (pe > 0)
    out["pe"] = pe.where(valid)                      # 0、負值一律清成 NaN
    out["pe_status"] = np.where(valid, PE_NORMAL, PE_UNPROFITABLE)
    out["pe_sort"] = out["pe"].fillna(np.inf)
    return out


# --------------------------------------------------------------------------
# 產業基準
# --------------------------------------------------------------------------
def industry_benchmark(df: pd.DataFrame, method: str = "median") -> float:
    """單一產業的本益比基準值。

    預設用中位數：台股單一產業常有一兩檔本益比破百的個股，
    平均值會被拉高到幾乎每檔都「低於平均」，篩選就失去意義。
    """
    pe = pd.to_numeric(df.get("pe"), errors="coerce").dropna()
    pe = pe[(pe > 0) & (pe <= PE_OUTLIER_CAP)]
    if pe.empty:
        return float("nan")
    return float(pe.mean() if method == "mean" else pe.median())


def industry_summary(df: pd.DataFrame, method: str = "median") -> pd.DataFrame:
    """各產業的估值與動能總覽（用於首頁儀表板）。"""
    rows = []
    for industry, g in df.groupby("industry", sort=False):
        pe = pd.to_numeric(g["pe"], errors="coerce")
        valid = pe[(pe > 0) & (pe <= PE_OUTLIER_CAP)]
        above = g["above_quarter_ma"] if "above_quarter_ma" in g else pd.Series(dtype=bool)
        rows.append({
            "產業": industry,
            "成分股數": len(g),
            "本益比基準": industry_benchmark(g, method),
            "最低本益比": float(valid.min()) if not valid.empty else np.nan,
            "PE分位中位數": (float(pd.to_numeric(g["pe_pctile"], errors="coerce").median())
                             if "pe_pctile" in g else np.nan),
            "未獲利檔數": int((g["pe_status"] == PE_UNPROFITABLE).sum()) if "pe_status" in g else 0,
            "站上季線比例": float(above.mean()) if len(above.dropna()) else np.nan,
            "平均漲跌幅": float(pd.to_numeric(g["change_pct"], errors="coerce").mean()),
            "低基期檔數": int(g["is_candidate"].sum()) if "is_candidate" in g else 0,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 技術面欄位
# --------------------------------------------------------------------------
def add_technical_flags(df: pd.DataFrame, ma_tolerance: float = 0.0) -> pd.DataFrame:
    """加上季線乖離、距 52 週高點回檔幅度等衍生欄位。"""
    out = df.copy()
    close = pd.to_numeric(out.get("close"), errors="coerce")
    ma_q = pd.to_numeric(out.get("ma_quarter"), errors="coerce")
    high = pd.to_numeric(out.get("high_52w"), errors="coerce")
    low = pd.to_numeric(out.get("low_52w"), errors="coerce")

    out["ma_bias_pct"] = ((close - ma_q) / ma_q * 100).where(ma_q > 0)
    # 容忍度：0.03 代表「跌破季線 3% 以內仍算站上」，用來抓剛回檔到季線附近的標的
    out["above_quarter_ma"] = (close >= ma_q * (1 - ma_tolerance)).where(
        close.notna() & ma_q.notna())
    out["drawdown_pct"] = ((high - close) / high * 100).where(high > 0)
    out["off_low_pct"] = ((close - low) / low * 100).where(low > 0)
    return out


# --------------------------------------------------------------------------
# 低基期篩選
# --------------------------------------------------------------------------
def screen_low_base(df: pd.DataFrame,
                    benchmark: Optional[float] = None,
                    method: str = "median",
                    ma_tolerance: float = 0.0,
                    min_pullback: float = 0.0,
                    require_ma: bool = True,
                    max_pe: Optional[float] = None) -> pd.DataFrame:
    """標記「低基期潛力股」。

    條件（可在側邊欄調整）：
      1. 本益比為正，且低於所屬產業基準（中位數或平均數）
      2. 股價站上季線（可設容忍度）—— 估值便宜但趨勢未壞
      3. 距 52 週高點已回檔至少 min_pullback %
      4. 本益比不超過 max_pe（絕對上限，選填）

    未獲利／負值的個股一律不列為候選：沒有 E，本益比低就沒有意義。
    """
    out = add_technical_flags(df, ma_tolerance)
    if benchmark is None:
        benchmark = industry_benchmark(out, method)

    pe = pd.to_numeric(out["pe"], errors="coerce")
    cond_pe = pe.notna() & (pe > 0)
    if pd.notna(benchmark):
        cond_pe &= pe < benchmark
    if max_pe is not None:
        cond_pe &= pe <= max_pe

    cond_ma = out["above_quarter_ma"].fillna(False) if require_ma else pd.Series(True, index=out.index)
    cond_dd = (pd.to_numeric(out["drawdown_pct"], errors="coerce") >= min_pullback) \
        if min_pullback > 0 else pd.Series(True, index=out.index)

    out["pe_vs_benchmark"] = (pe / benchmark - 1) * 100 if pd.notna(benchmark) else np.nan
    out["benchmark"] = benchmark
    out["hit_pe"] = cond_pe
    out["hit_ma"] = cond_ma
    out["hit_pullback"] = cond_dd
    out["is_candidate"] = cond_pe & cond_ma & cond_dd

    # 低基期分數：估值折價 + 距高點回檔，各半，越高越「低基期」
    disc = (-out["pe_vs_benchmark"]).clip(lower=0, upper=100)
    dd = pd.to_numeric(out["drawdown_pct"], errors="coerce").clip(lower=0, upper=100)
    out["low_base_score"] = (disc.fillna(0) * 0.5 + dd.fillna(0) * 0.5).round(1)

    # 沒過的是哪幾條 —— 三個 hit_* 旗標本來就算好了，不顯示等於白算，
    # 使用者只會看到「不在名單裡」卻不知道要放寬哪個滑桿。
    out["miss_reason"] = [
        "、".join(lbl for lbl, ok in (("估值", pe_ok), ("季線", ma_ok), ("回檔", dd_ok)) if not ok)
        for pe_ok, ma_ok, dd_ok in zip(cond_pe.fillna(False), cond_ma.fillna(False),
                                       cond_dd.fillna(False))]
    return out


# --------------------------------------------------------------------------
# 本益比歷史分位
# --------------------------------------------------------------------------
# 樣本數低於此值就不給分位：十幾天的資料算出來的「分位」只是雜訊，
# 顯示成一個看似精確的數字反而誤導。
MIN_PE_HISTORY_SAMPLES = 30

# 分位的回顧窗長（日曆日）。400 天≈一年再多一點，容得下連假與零星缺漏的快照。
PE_HISTORY_WINDOW_DAYS = 400


def add_pe_percentile(df: pd.DataFrame, history: pd.DataFrame,
                      as_of: Optional[str] = None,
                      window_days: int = PE_HISTORY_WINDOW_DAYS,
                      min_samples: int = MIN_PE_HISTORY_SAMPLES) -> pd.DataFrame:
    """加上「目前本益比落在該股自身歷史分佈的第幾百分位」。

    0 = 史上最便宜、100 = 史上最貴。這是縱向比較，補產業橫向比較的不足：
    整個族群都貴的時候，「低於同業中位數」仍可能是一檔絕對值很貴的股票。

    as_of（YYYYMMDD）務必傳入所選的交易日：母體只取該日「以前」的快照。
    不設限的話，回看 2025 年的某一天時會把 2026 年的本益比也算進母體 ——
    那是拿還沒發生的資料回頭評價當時的貴賤，結論會失真且偏樂觀。

    window_days 再把母體限制在近一年，讓它是「一年分位」而不是「開檔以來分位」：
    產業景氣循環會讓三年前的本益比水準失去可比性，而且快照愈積愈多時，
    久遠的資料會逐漸稀釋掉近期的變化。

    另外回傳 pe_hist_low / pe_hist_high（區間）與 pe_hist_n（樣本數），
    讓使用者能自己判斷這個分位有多少參考價值。
    """
    out = df.copy()
    cols = ["pe_pctile", "pe_hist_low", "pe_hist_high", "pe_hist_n"]
    if history is None or history.empty or "pe" not in history.columns:
        for c in cols:
            out[c] = np.nan
        return out

    h = history.copy()
    if as_of:
        h = h[h["date"] <= as_of]
        if window_days:
            start = (pd.Timestamp(as_of) - pd.Timedelta(days=window_days)).strftime("%Y%m%d")
            h = h[h["date"] >= start]
    h["pe"] = pd.to_numeric(h["pe"], errors="coerce")
    h = h[h["pe"] > 0]
    sorted_pe = {code: np.sort(g["pe"].to_numpy())
                 for code, g in h.groupby(h["code"].astype(str))}

    cur = pd.to_numeric(out.get("pe"), errors="coerce")
    pct, lo, hi, n = [], [], [], []
    for code, v in zip(out["code"].astype(str), cur):
        vals = sorted_pe.get(code)
        if vals is None or len(vals) < min_samples:
            pct.append(np.nan); lo.append(np.nan); hi.append(np.nan)
            n.append(0 if vals is None else len(vals))
            continue
        lo.append(float(vals[0])); hi.append(float(vals[-1])); n.append(len(vals))
        # side="right"：與自己相等的歷史值算在「不比現在貴」那邊
        pct.append(np.nan if pd.isna(v)
                   else float(np.searchsorted(vals, v, side="right")) / len(vals) * 100)

    out["pe_pctile"] = pct
    out["pe_hist_low"] = lo
    out["pe_hist_high"] = hi
    out["pe_hist_n"] = n
    return out


def sort_by_pe(df: pd.DataFrame, ascending: bool = True) -> pd.DataFrame:
    """依本益比由低至高排序；未獲利／負值一律排在最後。"""
    key = "pe_sort" if "pe_sort" in df.columns else "pe"
    return df.sort_values(key, ascending=ascending, kind="mergesort").reset_index(drop=True)
