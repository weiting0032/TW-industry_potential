#!/usr/bin/env python3
"""把 INDUSTRY_MAP 的成分股拿去跟交易所實際掛牌清單對帳。

為什麼需要這支：產業字典是手寫的，而個股會下市、改名、從上櫃轉上市。
一旦代號對不上，pipeline 的 merge 不會報錯，只會安靜地留下一整列 NaN ——
畫面上看起來就只是「這檔沒有本益比」，很難聯想到是分類表過期了。

用法：
    python scripts/check_universe.py            # 對最近交易日
    python scripts/check_universe.py 20260901   # 對指定日

離開碼：0 全部相符；1 有代號查無、市場別標錯，或抓不到交易所清單。
（名稱不一致只提醒不算錯 —— 交易所的簡稱偶爾會有全形空白之類的差異。）
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 主控台的系統 codepage 印中文會直接炸掉，先轉成 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from aistock.industry import all_stocks                    # noqa: E402
from aistock.pipeline import fetch_market_snapshot         # noqa: E402


def main() -> int:
    """走 fetch_market_snapshot 而不是直接呼叫 twse/tpex：它會讀 data/cache 的
    全市場快照。排程把這支排在 fetch_daily「之後」，就能重用剛剛抓下來的資料，
    不必為了對帳再下載一次 4.5 MB 的收盤行情。"""
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    target = dt.datetime.strptime(arg, "%Y%m%d").date() if arg else None

    day, market = fetch_market_snapshot(target)
    if day is None or market is None:
        print("✗ 抓不到全市場清單，無法對帳")
        return 1

    listed = {}
    for code, name, mk in zip(market["code"], market["name"], market["market"]):
        listed[str(code).strip()] = (str(name).strip(), str(mk).strip())

    # 先確認每個市場都真的抓到了。少了一整個交易所卻照常逐檔比對的話，
    # 畫面上會是「幾十檔上櫃股同時下市」—— 訊息完全指錯方向。
    universe_markets = {s.market for s in all_stocks()}
    listed_markets = {mk for _, mk in listed.values()}
    if universe_markets - listed_markets:
        absent = "、".join(sorted(universe_markets - listed_markets))
        print(f"✗ 清單裡完全沒有 {absent} 的個股 —— 是該交易所的資料沒抓到，"
              f"不是成分股有問題。請確認網路與 API 狀態後重跑，不要據此修改產業字典。")
        return 1

    missing, wrong_market, renamed = [], [], []
    for s in all_stocks():
        if s.code not in listed:
            missing.append(s)
            continue
        real_name, real_market = listed[s.code]
        if real_market != s.market:
            wrong_market.append((s, real_market))
        if real_name != s.name:
            renamed.append((s, real_name))

    total = len(all_stocks())
    print(f"對帳日 {day}｜成分股 {total} 檔｜"
          f"交易所掛牌 {len(listed)} 檔")

    for s in missing:
        print(f"  ✗ 查無代號 {s.code} {s.name}（{s.market}／{s.role}）—— 可能已下市或代號有誤")
    for s, real in wrong_market:
        print(f"  ✗ 市場別錯誤 {s.code} {s.name}：字典寫 {s.market}，實際為 {real}")
    for s, real in renamed:
        print(f"  ⚠ 名稱不一致 {s.code}：字典「{s.name}」，交易所「{real}」")

    if not (missing or wrong_market or renamed):
        print("  ✓ 代號、市場別、名稱全部相符")

    return 1 if (missing or wrong_market) else 0


if __name__ == "__main__":
    sys.exit(main())
