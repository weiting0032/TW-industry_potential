#!/usr/bin/env python3
"""排程進入點：抓取最近一個交易日的資料，寫入 data/snapshots/。

由 .github/workflows/daily.yml 每個交易日收盤後執行，
產出的 parquet 會被 commit 進 repo，供 Streamlit Cloud 的 App 直接讀取。

用法：
    python scripts/fetch_daily.py              # 抓最近交易日（已存在則略過）
    python scripts/fetch_daily.py 20260828     # 指定日期
    python scripts/fetch_daily.py --backfill 5 # 回補最近 5 個交易日
    python scripts/fetch_daily.py --force      # 已存在也重抓（財報更新後覆蓋用）

預設「已完整就略過」——注意是「完整」而不是「存在」。
交易所的本益比 API（TWSE BWIBBU_d / TPEx peQryDate）比收盤行情晚公布，
太早跑會寫出有價無本益比的空殼快照；若只看檔案在不在就略過，
後面的補跑班次不會修它，該交易日的資料就永久壞在那裡。

離開碼：
    0 成功，或今日本來就沒有新資料（假日）—— 不讓排程因為放假而變紅
    1 交易所回應異常，確實抓取失敗
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aistock import snapshots                      # noqa: E402
from aistock.industry import all_stocks            # noqa: E402
from aistock.pipeline import (recent_trading_days, resolve_trading_day,   # noqa: E402
                              store_snapshot)

# Windows 主控台預設用系統 codepage（cp950 / cp1252）編碼，印中文會直接
# UnicodeEncodeError 炸掉整支腳本 —— 而且是在快照已寫入之後才炸，
# 表面看起來失敗、實際上成功，最容易誤判。GitHub Actions 的 Linux 是 UTF-8 不受影響。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("fetch_daily")


def _fmt(day: str) -> str:
    return f"{day[:4]}/{day[4:6]}/{day[6:8]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="YYYYMMDD，省略則抓最近交易日")
    ap.add_argument("--backfill", type=int, default=0, metavar="N",
                    help="回補最近 N 個交易日")
    ap.add_argument("--force", action="store_true",
                    help="快照已存在時仍重新抓取（預設略過，讓排程可重跑不重工）")
    args = ap.parse_args()

    if args.backfill:
        wanted = recent_trading_days(args.backfill)
        log.info("回補區間 %s ~ %s（%d 個交易日）",
                 _fmt(wanted[0]), _fmt(wanted[-1]), len(wanted))
        targets = [dt.datetime.strptime(d, "%Y%m%d").date() for d in wanted]
    elif args.date:
        targets = [dt.datetime.strptime(args.date, "%Y%m%d").date()]
    else:
        targets = [None]

    universe = {s.code for s in all_stocks()}
    log.info("成分股 %d 檔", len(universe))
    written, skipped, failed = [], [], []
    for target in targets:
        day = resolve_trading_day(target)
        if day is None:
            log.warning("查無交易日（%s），可能是連假或日期過早", target)
            skipped.append(str(target))
            continue

        if not args.force and snapshots.is_complete(day, universe):
            log.info("%s 快照已完整，略過", day)
            skipped.append(day)
            continue

        if snapshots.path_for(day).exists():
            old = snapshots.load(day)
            log.info("%s 快照不完整（成分股 %d/%d、本益比覆蓋率 %.0f%%），重抓修補",
                     day, old["code"].nunique(), len(universe),
                     snapshots.min_market_pe_coverage(old) * 100)
        log.info("抓取 %s …", day)
        result, saved = store_snapshot(
            target if target else dt.datetime.strptime(day, "%Y%m%d").date())
        if result is None:
            log.error("%s 抓取失敗", day)
            failed.append(day)
        elif not saved:
            log.warning("⏸ %s 本次抓到的資料較差，保留既有快照", result)
            failed.append(result)          # 仍算失敗：這天的資料還沒補齊，排程該紅
        else:
            size = snapshots.path_for(result).stat().st_size / 1024
            log.info("✅ %s 已寫入（%.1f KB，%d 檔，本益比覆蓋率 %.0f%%）", result, size,
                     snapshots.load(result)["code"].nunique(),
                     snapshots.min_market_pe_coverage(snapshots.load(result)) * 100)
            written.append(result)

    # 「有寫入」不等於「資料完整」：交易所本益比公布得晚，下午的班次本來就會拿到
    # 半套資料。這不算失敗（下一班會自動修補），但一定要在結論行講出來，
    # 否則排程一片綠燈、資料卻是缺的，沒人會發現。
    incomplete = [d for d in written if not snapshots.is_complete(d, universe)]
    print(f"\n寫入 {len(written)} 筆 {written} ｜ 略過 {len(skipped)} ｜ 失敗 {len(failed)}")
    if incomplete:
        print(f"⚠ 其中 {len(incomplete)} 份仍不完整 {incomplete} "
              f"—— 交易所尚未公布本益比，或該市場暫時抓不到；下一班會自動重抓修補")

    if failed:
        return 1
    # 沒有新資料（假日、或快照都已存在）不算失敗，排程不該因為放假變紅
    return 0


if __name__ == "__main__":
    sys.exit(main())
