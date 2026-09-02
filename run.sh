#!/usr/bin/env bash
# 一鍵啟動：建立虛擬環境（若不存在）、安裝相依套件、開啟 App
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "▶ 建立虛擬環境 .venv"
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-fetch.txt

echo "▶ 啟動 Streamlit (http://localhost:8501)"
exec streamlit run app.py
