"""台股 AI 產業鏈 —— 每日本益比追蹤選股 App。

啟動：streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
import io

import pandas as pd
import streamlit as st

from aistock import cache, snapshots, view
from aistock.analysis import (MIN_PE_HISTORY_SAMPLES, PE_UNPROFITABLE,
                              add_pe_percentile, classify_pe,
                              industry_benchmark, industry_summary,
                              screen_low_base, sort_by_pe)
from aistock.config import (DEFAULT_MA_TOLERANCE, DEFAULT_MIN_PULLBACK,
                            DEFAULT_PE_BENCHMARK, SNAPSHOT_ONLY)
from aistock.industry import INDUSTRY_MAP, all_stocks, industry_names
from aistock.pipeline import load_dataset

st.set_page_config(page_title="台股 AI 產業鏈本益比追蹤",
                   page_icon="📉", layout="wide")


def _secret(name: str) -> str:
    """讀 st.secrets 的單一鍵值，讀不到一律回空字串。

    Streamlit Community Cloud 沒有環境變數介面，也不會把 secrets 注入 os.environ，
    所以設定要兩條管道都支援；而本機沒有 secrets.toml 時 st.secrets 會直接拋例外。
    """
    try:
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""


# 強制快照模式：環境變數（本機／Docker／VPS）或 secrets（Streamlit Cloud）
FORCE_SNAPSHOT = SNAPSHOT_ONLY or _secret("AISEMI_SNAPSHOT_ONLY") in ("1", "true", "True")
SNAPSHOT_DAYS = snapshots.available_dates()
UNIVERSE_CODES = {s.code for s in all_stocks()}


# --------------------------------------------------------------------------
# 資料載入
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=60 * 60 * 6)
def load_data(date_key: str, refresh_token: int, mode: str):
    """date_key: 'latest' 或 YYYYMMDD；refresh_token 變動即強制重抓。"""
    target = None if date_key == "latest" else dt.datetime.strptime(date_key, "%Y%m%d").date()
    trade_day, df, source = load_dataset(target, mode=mode,
                                         force_refresh=refresh_token > 0)
    if df is None:
        return None, None, source
    return trade_day, classify_pe(df), source


@st.cache_data(show_spinner=False, ttl=60 * 60 * 6)
def load_pe_history(fingerprint: str) -> pd.DataFrame:
    """歷來快照的本益比長表。fingerprint 只是讓快取隨快照數量變動而失效的鍵。"""
    return snapshots.pe_history()


def fmt_day(day: str) -> str:
    return f"{day[:4]}/{day[4:6]}/{day[6:8]}"


def weekdays_between(start: dt.date, end: dt.date) -> int:
    """兩個日期之間隔了幾個平日，用來判斷排程是不是已經斷了好幾天。

    刻意不查交易所行事曆（快照模式的原則是完全不連外），
    因此國定假日也會被算成平日 —— 門檻設寬一點即可，這裡只需要「有沒有異常」的量級。
    """
    return sum(1 for i in range((end - start).days)
               if (start + dt.timedelta(days=i + 1)).weekday() < 5)


# --------------------------------------------------------------------------
# 側邊欄
# --------------------------------------------------------------------------
st.sidebar.title("📉 台股 AI 產業鏈選股")

if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = 0

nav = st.sidebar.radio("檢視模式", ["產業明細", "低基期總表", "產業總覽"], index=0)

industry = st.sidebar.selectbox("次產業", industry_names(),
                                disabled=(nav != "產業明細"))

query = st.sidebar.text_input(
    "🔍 搜尋代號或名稱", placeholder="例如 2330 或 台積電",
    help="留空表示不過濾。搜尋只影響表格內容，產業基準仍以完整成分股計算")

st.sidebar.divider()
st.sidebar.subheader("資料來源")

# 快照優先：只要 repo 裡有快照就預設讀快照。
# 這樣即使部署時忘了設 AISEMI_SNAPSHOT_ONLY，雲端也不會從國外 IP 傻傻地直打交易所。
if FORCE_SNAPSHOT:
    mode = "snapshot"
    st.sidebar.caption("📦 快照模式（由設定強制，不對外連線）")
elif SNAPSHOT_DAYS:
    src_label = st.sidebar.radio(
        "讀取方式", ["每日快照", "即時擷取"], index=0, horizontal=True,
        help="快照由 GitHub Actions 每個交易日收盤後更新並 commit 進 repo；"
             "即時擷取會直接連證交所與櫃買中心，較慢且可能被限流")
    mode = "snapshot" if src_label == "每日快照" else "live"
else:
    mode = "live"
    st.sidebar.caption("⚠️ 尚無任何快照，改用即時擷取")

if mode == "snapshot":
    labels = {d: fmt_day(d) for d in reversed(SNAPSHOT_DAYS)}
    # 預設選「最近一份完整的」而不是「最新的」：收盤到交易所公布本益比之間
    # 有數小時空窗，那段時間的最新快照只有價量，預設顯示它等於預設顯示一片「—」。
    default_day = snapshots.latest_complete_date(UNIVERSE_CODES) or SNAPSHOT_DAYS[-1]
    date_key = st.sidebar.selectbox(
        "交易日", list(labels), format_func=labels.get,
        index=list(labels).index(default_day),
        help="可選日期即已抓取的快照；資料由排程每個交易日收盤後更新")
    st.sidebar.caption(f"📦 已收錄 {len(SNAPSHOT_DAYS)} 個交易日")
    if default_day != SNAPSHOT_DAYS[-1]:
        st.sidebar.caption(f"ℹ️ {fmt_day(SNAPSHOT_DAYS[-1])} 的本益比交易所尚未公布，"
                           "預設顯示前一個完整交易日")
else:
    use_latest = st.sidebar.checkbox("使用最近交易日", value=True)
    picked = st.sidebar.date_input("指定日期", value=dt.date.today(),
                                   max_value=dt.date.today(), disabled=use_latest)
    date_key = "latest" if use_latest else picked.strftime("%Y%m%d")

    col_a, col_b = st.sidebar.columns(2)
    if col_a.button("🔄 重新抓取", width="stretch"):
        st.session_state.refresh_token += 1
        st.cache_data.clear()
        st.rerun()
    if col_b.button("🗑️ 清空快取", width="stretch"):
        n = cache.clear()
        st.cache_data.clear()
        st.sidebar.success(f"已清除 {n} 個快取檔")
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("🎯 尋找低檔標的")
bench_label = st.sidebar.radio(
    "產業本益比基準", ["中位數", "平均數"],
    index=0 if DEFAULT_PE_BENCHMARK == "median" else 1, horizontal=True,
    help="中位數較能抵抗單一高本益比個股拉高基準的影響")
method = "median" if bench_label == "中位數" else "mean"

require_ma = st.sidebar.checkbox("要求股價站上季線 (MA60)", value=True)
ma_tol = st.sidebar.slider("季線容忍度 (%)", 0.0, 15.0, DEFAULT_MA_TOLERANCE * 100, 0.5,
                           help="允許跌破季線的幅度；設 3% 可納入剛回測季線的個股",
                           disabled=not require_ma) / 100
min_pullback = st.sidebar.slider("距 52 週高點至少回檔 (%)", 0.0, 60.0,
                                 DEFAULT_MIN_PULLBACK, 5.0)
use_cap = st.sidebar.checkbox("設定本益比絕對上限", value=False)
max_pe = st.sidebar.slider("本益比上限", 5.0, 120.0, 40.0, 1.0,
                           disabled=not use_cap)

screen_kwargs = dict(method=method, ma_tolerance=ma_tol,
                     min_pullback=min_pullback, require_ma=require_ma,
                     max_pe=max_pe if use_cap else None)


# --------------------------------------------------------------------------
# 主畫面
# --------------------------------------------------------------------------
_spinner = "讀取每日快照中…" if mode == "snapshot" else "擷取證交所／櫃買中心收盤資料中…"
with st.spinner(_spinner):
    trade_day, data, source = load_data(date_key, st.session_state.refresh_token, mode)

if data is None:
    if mode == "snapshot":
        st.error("尚無任何快照。資料由 GitHub Actions 每個交易日收盤後更新 —— "
                 "請確認排程已成功執行，或手動觸發 workflow 補跑。")
    else:
        st.error("查無資料。可能是連續假期、日期過早，或交易所 API 暫時無回應 —— "
                 "請按左側「重新抓取」再試一次。")
    st.stop()

# 本益比歷史分位：母體是歷來快照公告的本益比，純讀本地檔案。
# as_of 一定要給所選交易日 —— 回看過去某一天時，母體不能含當天之後的資料。
pe_hist = load_pe_history(f"{len(SNAPSHOT_DAYS)}:{SNAPSHOT_DAYS[-1] if SNAPSHOT_DAYS else '-'}")
data = add_pe_percentile(data, pe_hist, as_of=trade_day)

# 逐產業套用篩選（基準值必須以各自產業計算，所以要在搜尋過濾「之前」做）
scored = pd.concat(
    [screen_low_base(g, **screen_kwargs) for _, g in data.groupby("industry", sort=False)],
    ignore_index=True)

st.title("台股 AI 產業鏈 · 本益比追蹤")

# ---- 資料健康度：排程斷掉、或交易所當日還沒公布本益比，都要一眼看得出來 ----
unique_rows = scored.drop_duplicates(subset="code")
coverage = snapshots.min_market_pe_coverage(unique_rows)

_src = "📦 每日快照" if source == "snapshot" else "🌐 即時擷取"
st.caption(
    f"資料日期 **{fmt_day(trade_day)}** ｜ {_src} ｜ "
    f"成分股 {len(unique_rows)} 檔／{scored['industry'].nunique()} 個次產業 ｜ "
    f"本益比覆蓋率 {coverage:.0%} ｜ 本益比與收盤價來源：臺灣證券交易所、"
    f"證券櫃檯買賣中心公告 ｜ 均線與 52 週高低點由歷史收盤價計算")

if SNAPSHOT_DAYS:
    lag = weekdays_between(dt.datetime.strptime(SNAPSHOT_DAYS[-1], "%Y%m%d").date(),
                           dt.date.today())
    if lag >= 4:
        st.warning(
            f"⚠️ 最新快照停在 **{fmt_day(SNAPSHOT_DAYS[-1])}**，距今已隔 {lag} 個平日沒有更新。"
            "請到 GitHub 的 Actions 分頁確認排程狀態 —— "
            "repo 連續 60 天沒有任何 commit，GitHub 會自動停用排程工作流程。")

if coverage < 0.5:
    st.warning(
        f"⚠️ 本日本益比覆蓋率僅 **{coverage:.0%}**（上市／上櫃分別計算後取較低者）。"
        "交易所的本益比 API 公布時間比收盤行情晚，若這是當日資料，稍後重跑排程即可補齊。")

# ---- 搜尋過濾（在產業基準算完之後才套用，才不會扭曲基準） ----
if query.strip():
    q = query.strip()
    hit = (scored["code"].astype(str).str.contains(q, case=False, na=False, regex=False)
           | scored["name"].astype(str).str.contains(q, case=False, na=False, regex=False))
    scored = scored[hit]
    if scored.empty:
        st.info(f"🔍 找不到符合「{q}」的成分股。清空左側搜尋框即可看完整清單。")
        st.stop()
    st.info(f"🔍 只顯示符合「{q}」的 {scored['code'].nunique()} 檔"
            "（產業基準仍以完整成分股計算）")

_pctile_help = ("PE歷史分位 ＝ 本益比在該股「自身近一年分佈」中的位置，0 = 一年來最便宜。"
                f"母體只取所選交易日以前的快照，樣本不足 {MIN_PE_HISTORY_SAMPLES} 個交易日時顯示「—」。")


# ---------------------------- 產業明細 ----------------------------
if nav == "產業明細":
    g = sort_by_pe(scored[scored.industry == industry])
    if g.empty:
        st.info(f"「{industry}」沒有符合目前搜尋條件的成分股。")
        st.stop()

    bench = industry_benchmark(g, method)
    valid_pe = pd.to_numeric(g["pe"], errors="coerce").dropna()
    pctile = pd.to_numeric(g["pe_pctile"], errors="coerce").dropna()

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("成分股", f"{len(g)} 檔")
    m2.metric(f"產業本益比{bench_label}", f"{bench:.2f}" if pd.notna(bench) else "—")
    m3.metric("最低本益比", f"{valid_pe.min():.2f}" if not valid_pe.empty else "—")
    m4.metric("PE分位中位數", f"{pctile.median():.0f}" if not pctile.empty else "—",
              help=_pctile_help)
    m5.metric("未獲利／負值", f"{int((g.pe_status == PE_UNPROFITABLE).sum())} 檔")
    m6.metric("低基期候選", f"{int(g.is_candidate.sum())} 檔")

    st.subheader(f"{industry} ── 依本益比由低至高")
    st.caption("🟡 黃底 = 符合低基期條件　｜　灰字 = 未獲利／負值（排序置底）　｜　"
               "「未達標項」列出還差哪一條，對應左側可調整的滑桿")
    disp = view.to_display(g)
    st.dataframe(view.style(disp), width="stretch",
                 height=min(80 + 36 * len(g), 640))

    hits = g[g.is_candidate]
    st.subheader("🎯 低基期潛力股")
    if hits.empty:
        st.info("目前沒有個股同時滿足所有條件，可放寬左側的季線容忍度或回檔門檻。")
    else:
        for _, r in sort_by_pe(hits).iterrows():
            with st.container(border=True):
                c1, c2, c3, c4, c5 = st.columns([2.2, 1, 1, 1, 1])
                c1.markdown(f"**{r['code']} {r['name']}**　`{r['role']}`")
                c2.metric("本益比", f"{r['pe']:.2f}",
                          f"{r['pe_vs_benchmark']:+.1f}% vs 基準")
                c3.metric("PE歷史分位",
                          f"{r['pe_pctile']:.0f}" if pd.notna(r["pe_pctile"]) else "—",
                          (f"區間 {r['pe_hist_low']:.0f}–{r['pe_hist_high']:.0f}"
                           if pd.notna(r["pe_hist_low"])
                           else f"樣本僅 {int(r['pe_hist_n'])} 日"),
                          delta_color="off")
                c4.metric("收盤價", f"{r['close']:,.2f}",
                          f"{r['change_pct']:+.2f}%" if pd.notna(r['change_pct']) else None)
                c5.metric("季線乖離", f"{r['ma_bias_pct']:+.2f}%",
                          f"距高點 -{r['drawdown_pct']:.1f}%", delta_color="off")

    with st.expander("本產業成分股與供應鏈定位"):
        st.dataframe(pd.DataFrame(
            [{"代號": s.code, "名稱": s.name,
              "市場": "上市" if s.market == "TWSE" else "上櫃", "定位": s.role}
             for s in INDUSTRY_MAP[industry]]),
            width="stretch", hide_index=True)

    out = g

# ---------------------------- 低基期總表 ----------------------------
elif nav == "低基期總表":
    hits = sort_by_pe(scored[scored.is_candidate]).drop_duplicates(
        subset=["code", "industry"])
    st.subheader("🎯 全產業低基期潛力股")
    st.caption("跨全部次產業，符合「本益比低於所屬產業基準 + 技術面條件」的個股")

    _p = (pd.to_numeric(hits["pe_pctile"], errors="coerce").dropna()
          if not hits.empty else pd.Series(dtype=float))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("符合檔數", f"{hits['code'].nunique()} 檔")
    c2.metric("涵蓋產業", f"{hits['industry'].nunique()} 個")
    c3.metric("平均本益比",
              f"{pd.to_numeric(hits['pe'], errors='coerce').mean():.2f}"
              if not hits.empty else "—")
    c4.metric("PE分位中位數", f"{_p.median():.0f}" if not _p.empty else "—",
              help=_pctile_help)

    if hits.empty:
        st.info("目前沒有符合條件的個股，請放寬左側篩選條件。")
    else:
        disp = view.to_display(hits)
        disp.insert(0, "產業", hits["industry"].to_numpy())
        st.dataframe(view.style(disp), width="stretch",
                     height=min(80 + 36 * len(hits), 700))

        st.subheader("低基期分數排行")
        rank = hits.sort_values("low_base_score", ascending=False).head(15)
        st.bar_chart(rank.set_index(rank["code"] + " " + rank["name"])["low_base_score"],
                     horizontal=True, height=420)
    out = hits

# ---------------------------- 產業總覽 ----------------------------
else:
    summary = industry_summary(scored, method).sort_values("本益比基準")
    st.subheader("各次產業估值比較")
    st.caption(_pctile_help)

    st.dataframe(view.style_summary(summary), width="stretch", hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**產業本益比基準（越低越便宜）**")
        st.bar_chart(summary.set_index("產業")["本益比基準"], horizontal=True, height=420)
    with c2:
        st.markdown("**各產業低基期候選檔數**")
        st.bar_chart(summary.set_index("產業")["低基期檔數"], horizontal=True, height=420)

    st.subheader("全體成分股 · 本益比由低至高")
    allrows = sort_by_pe(scored).drop_duplicates(subset="code")
    disp = view.to_display(allrows)
    disp.insert(0, "產業", allrows["industry"].to_numpy())
    st.dataframe(view.style(disp), width="stretch", height=640)
    out = allrows

# ---------------------------- 下載與聲明 ----------------------------
st.divider()
# 下載檔沿用畫面上的中文欄名，而不是內部欄名 —— code / pe / ma60 對非開發者沒有意義
csv_df = view.to_display(out).drop(columns=["_candidate"], errors="ignore")
if "industry" in out.columns:
    csv_df.insert(0, "產業", out["industry"].to_numpy())
buf = io.StringIO()
csv_df.to_csv(buf, index=False)
st.download_button("⬇️ 下載目前表格 (CSV)", buf.getvalue(),
                   file_name=f"tw_ai_pe_{trade_day}.csv", mime="text/csv")

st.caption(
    "⚠️ 本工具僅整理公開資訊供研究參考，不構成任何投資建議或買賣要約。"
    "交易所公告之本益比採「近四季每股盈餘」計算，屬落後指標，"
    "遇一次性業外收益、產業景氣轉折或財報更新時可能嚴重失真；"
    "產業分類為自訂主觀歸類，非官方定義。投資決策與風險請自行評估。")
