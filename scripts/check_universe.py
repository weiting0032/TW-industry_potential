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
from aistock.pipeline import resolve_trading_day           # noqa: E402
from aistock.sources import tpex, twse                     # noqa: E402


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else resolve_trading_day()
    if day is None:
        print("✗ 查不到可用交易日，無法對帳")
        return 1

    listed = {}
    for df, market in ((twse.fetch(day), "TWSE"), (tpex.fetch(day), "TPEx")):
        if df is None:
            print(f"✗ {market} 清單抓取失敗")
            return 1
        for code, name in zip(df["code"], df["name"]):
            listed[str(code).strip()] = (str(name).strip(), market)

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
