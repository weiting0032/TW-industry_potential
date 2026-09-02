"""表格呈現：欄位命名、數值格式化、低基期高亮。

關於缺值為什麼要自己轉字串：
  Streamlit 的表格前端把缺值一律畫成一個灰色的 "None"，
  而且 `Styler.format(na_rep="—")` 與 `st.column_config.NumberColumn` 都蓋不掉
  （實測 streamlit 1.62 + pandas 3.0：純 DataFrame、Styler + na_rep、column_config
  三種寫法畫出來都是 "None"，只有「值本身已經是字串」才會照實顯示）。
  這個 App 的缺值是常態 —— 未獲利個股沒有本益比、歷史樣本不足沒有分位、
  當日交易所還沒公布時整欄都空 —— 一整片 "None" 看起來就像程式壞了。
  所以 style() 會在交給 Styler 之前先把整張表轉成字串。

  代價：前端點欄位標題排序會變成字典序（"13.36" 排在 "5.91" 前面）。
  可以接受，因為表格本來就已經由後端依本益比排好序。
  to_display() 則刻意「不」轉字串，讓 CSV 下載拿到的仍是可運算的數值。
"""
from __future__ import annotations

import pandas as pd

from .analysis import PE_UNPROFITABLE

# 缺值在畫面上的樣子
NA_TEXT = "—"

# 內部欄名 → 畫面欄名
DISPLAY_COLUMNS = [
    ("code", "股票代號"),
    ("name", "股票名稱"),
    ("market", "市場"),
    ("role", "供應鏈定位"),
    ("close", "收盤價"),
    ("change_pct", "漲跌幅(%)"),
    ("pe", "本益比"),
    ("pe_vs_benchmark", "vs 產業基準(%)"),
    ("pe_pctile", "PE歷史分位"),
    ("pb", "股價淨值比"),
    ("dividend_yield", "殖利率(%)"),
    ("ma_quarter", "季線"),
    ("ma_bias_pct", "季線乖離(%)"),
    ("drawdown_pct", "距52週高(%)"),
    ("low_base_score", "低基期分數"),
    ("pe_status", "本益比狀態"),
    ("miss_reason", "未達標項"),
    ("fiscal", "財報季別"),
]

NUMBER_FORMATS = {
    "收盤價": "{:,.2f}",
    "漲跌幅(%)": "{:+.2f}",
    "本益比": "{:.2f}",
    "vs 產業基準(%)": "{:+.1f}",
    "PE歷史分位": "{:.0f}",
    "股價淨值比": "{:.2f}",
    "殖利率(%)": "{:.2f}",
    "季線": "{:,.2f}",
    "季線乖離(%)": "{:+.2f}",
    "距52週高(%)": "{:.2f}",
    "低基期分數": "{:.1f}",
}

# 產業總覽表的欄位格式
SUMMARY_FORMATS = {
    "本益比基準": "{:.2f}",
    "最低本益比": "{:.2f}",
    "PE分位中位數": "{:.0f}",
    "站上季線比例": "{:.0%}",
    "平均漲跌幅": "{:+.2f}",
}

_HIGHLIGHT = "background-color: rgba(255, 193, 7, 0.28); font-weight: 600;"
_MUTED = "color: rgba(128, 128, 128, 0.85);"


def to_display(df: pd.DataFrame) -> pd.DataFrame:
    """挑出要顯示的欄位並改為中文欄名（保留 is_candidate 供高亮用）。

    刻意保持原本的數值型別 —— CSV 下載直接用這份，數字要還能運算。
    畫面用的字串化在 style() 裡才做。
    """
    df = df.reset_index(drop=True)   # Styler 的逐列高亮依賴連續索引
    cols = [(src, dst) for src, dst in DISPLAY_COLUMNS if src in df.columns]
    out = df[[src for src, _ in cols]].copy()
    out.columns = [dst for _, dst in cols]
    if "is_candidate" in df.columns:
        out["_candidate"] = df["is_candidate"].to_numpy()
    return out


def as_text(df: pd.DataFrame, formats: dict[str, str]) -> pd.DataFrame:
    """把整張表轉成字串：數值套格式、缺值換成「—」。

    空字串保持空字串（例如「未達標項」對入選個股本來就是空的），
    只有真正的缺值才顯示「—」。
    """
    out = pd.DataFrame(index=df.index)
    for col in df.columns:
        fmt = formats.get(col)
        if fmt:
            values = pd.to_numeric(df[col], errors="coerce")
            out[col] = [fmt.format(v) if pd.notna(v) else NA_TEXT for v in values]
        else:
            out[col] = [NA_TEXT if pd.isna(v) else str(v) for v in df[col]]
    return out


def style(display_df: pd.DataFrame):
    """回傳 Styler：低基期標的整列高亮、未獲利個股整列淡化。"""
    flags = display_df.get("_candidate")
    body = as_text(display_df.drop(columns=["_candidate"], errors="ignore"),
                   NUMBER_FORMATS)

    def row_style(row: pd.Series):
        if flags is not None and bool(flags.iloc[row.name]):
            return [_HIGHLIGHT] * len(row)
        if row.get("本益比狀態") == PE_UNPROFITABLE:
            return [_MUTED] * len(row)
        return [""] * len(row)

    return body.style.apply(row_style, axis=1)


def style_summary(summary: pd.DataFrame):
    """產業總覽表：先用數值算色階，再轉成字串交給 Styler。"""
    gradient = value_gradient(summary["本益比基準"])
    text = as_text(summary.reset_index(drop=True), SUMMARY_FORMATS)
    return text.style.apply(lambda _col: gradient, subset=["本益比基準"])


def value_gradient(series: pd.Series, reverse: bool = False) -> list[str]:
    """數值欄位的紅→綠背景色階（自行實作，避免為了配色引入 matplotlib）。

    reverse=False：值越低越綠（適合本益比，低=便宜）。
    """
    s = pd.to_numeric(series, errors="coerce")
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return [""] * len(s)

    out = []
    for v in s:
        if pd.isna(v):
            out.append("")
            continue
        t = (v - lo) / (hi - lo)          # 0 = 最低, 1 = 最高
        if reverse:
            t = 1 - t
        # 綠 (76,175,80) → 黃 (255,193,7) → 紅 (239,83,80)
        if t < 0.5:
            k = t / 0.5
            r, g, b = (76 + (255 - 76) * k, 175 + (193 - 175) * k, 80 + (7 - 80) * k)
        else:
            k = (t - 0.5) / 0.5
            r, g, b = (255 + (239 - 255) * k, 193 + (83 - 193) * k, 7 + (80 - 7) * k)
        out.append(f"background-color: rgba({r:.0f}, {g:.0f}, {b:.0f}, 0.30);")
    return out
