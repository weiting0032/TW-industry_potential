"""全域設定：路徑、快取、網路與篩選預設值。"""
from __future__ import annotations

import os
from pathlib import Path

# ---------- 路徑 ----------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"          # 暫時性快取，不進版控
SNAPSHOT_DIR = DATA_DIR / "snapshots"   # 每日快照，由排程 commit 進 repo
CACHE_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- 網路 ----------
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUEST_TIMEOUT = 40          # 單次請求逾時（秒）
REQUEST_GAP = 3.0             # 對同一主機的請求間隔（秒），避免被證交所擋
# 重試次數與退避基數。實測依據：2026-09-02 的 GitHub Actions 執行中，
# 櫃買中心連續回 HTTP 520（Cloudflare 端錯誤，不是 403 封鎖），
# 舊設定 3 次、退避 5s/10s 共只撐 15 秒就放棄 —— 但同一個 job 裡
# 一分鐘後的對帳步驟就抓成功了。也就是說失敗的原因是「等不夠久」。
# 現在 5 次、退避 6/12/18/24 秒，總共約 60 秒，足以跨過那種短暫的伺服器抖動。
MAX_RETRY = 5                 # 失敗重試次數
BACKOFF_BASE = 6.0            # 重試退避基數（秒）

# 從指定日往回找可用交易日的最大天數（涵蓋連假）
MAX_LOOKBACK_DAYS = 12

# ---------- 快取 ----------
DAILY_CACHE_TTL_HOURS = 12    # 當日快照快取時效
HISTORY_CACHE_TTL_HOURS = 20  # 歷史均線快取時效
# yfinance 抓取區間。取 3 年而非 1 年，是為了讓「回補歷史快照」也算得出技術面：
# 回補到一年前那天時，往前仍需 250 個交易日才有 52 週高低點與半年線。
# 收盤價寬表在同一個 process 內只下載一次，多抓兩年的成本可以忽略。
HISTORY_PERIOD = "3y"

# ---------- 均線 ----------
MA_WINDOWS = (20, 60, 120)    # 月線、季線、半年線
QUARTER_MA = 60               # 「季線」定義

# ---------- 執行模式 ----------
# AISEMI_SNAPSHOT_ONLY=1 時，App 只讀 data/snapshots/ 的快照，絕不對外抓取。
# 部署到 Streamlit Cloud 時設定此環境變數：資料由 GitHub Actions 排程更新，
# 前端不需要（也不應該）從雲端 IP 直接打證交所。
SNAPSHOT_ONLY = os.environ.get("AISEMI_SNAPSHOT_ONLY", "").strip() in ("1", "true", "True")

# ---------- 低基期篩選預設值 ----------
DEFAULT_PE_BENCHMARK = "median"   # "median" 或 "mean"
DEFAULT_MA_TOLERANCE = 0.0        # 站上季線的容忍度，0.03 代表允許跌破季線 3% 內
DEFAULT_MIN_PULLBACK = 0.0        # 距 52 週高點至少回檔幾 %
