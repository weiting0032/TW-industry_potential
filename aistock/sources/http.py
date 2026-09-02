"""共用的 HTTP 客戶端：內建節流、重試與 UA 偽裝。

證交所／櫃買中心對高頻請求會回 429 或直接斷線，
因此所有對外請求都經過此處統一節流。

關於企業網路的 TLS 攔截：
  公司內網常有中間盒把 HTTPS 拆開重簽。實測本機連 www.tpex.org.tw 會間歇性拿到
  `CERTIFICATE_VERIFY_FAILED: Missing Subject Key Identifier` ——
  代理重簽的憑證缺少 Subject Key Identifier 擴充欄位，OpenSSL 3.x 的嚴格檢查會拒絕，
  而 requests 預設只信任 certifi 內建清單、看不到企業 CA。
  安裝 truststore 後改用「作業系統憑證庫」驗證（企業 CA 本來就裝在那裡），
  問題即消失。這是換一個正確的信任來源，不是關閉驗證 —— 絕不要改成 verify=False。
  未安裝 truststore 時自動略過，GitHub Actions 與 Streamlit Cloud 不需要它。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

from ..config import BACKOFF_BASE, MAX_RETRY, REQUEST_GAP, REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

def _use_os_trust_store() -> None:
    """有裝 truststore 就改用作業系統憑證庫驗證 TLS（企業攔截代理環境需要）。"""
    try:
        import truststore
        truststore.inject_into_ssl()
        log.debug("已改用作業系統憑證庫驗證 TLS")
    except Exception:
        pass          # 沒裝或注入失敗都不該影響主流程，維持 certifi 預設行為


_use_os_trust_store()

_session: Optional[requests.Session] = None
_lock = threading.Lock()
_last_call: Dict[str, float] = {}   # host -> 上次請求時間


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        })
        _session = s
    return _session


def _throttle(host: str) -> None:
    """同一主機兩次請求至少間隔 REQUEST_GAP 秒。"""
    with _lock:
        prev = _last_call.get(host, 0.0)
        wait = REQUEST_GAP - (time.time() - prev)
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()


def get_json(url: str, params: Dict[str, Any], *, host_key: str) -> Optional[dict | list]:
    """帶重試的 JSON GET。全部失敗時回傳 None（而非拋例外），讓上層可降級處理。"""
    sess = _get_session()
    for attempt in range(1, MAX_RETRY + 1):
        _throttle(host_key)
        try:
            resp = sess.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                # 無資料的日期，交易所有時回空字串而非合法 JSON
                if not resp.text.strip():
                    return None
                return resp.json()
            # 5xx（含 Cloudflare 的 520~524）是對方伺服器的問題，重試通常會好；
            # 4xx 多半是參數或被擋，重試意義不大 —— 分開記，log 才看得出該怎麼處理。
            kind = "伺服器端錯誤，重試中" if resp.status_code >= 500 else "請求被拒"
            log.warning("%s 回應 %s（%s，第 %d/%d 次）",
                        host_key, resp.status_code, kind, attempt, MAX_RETRY)
        except (requests.RequestException, ValueError) as exc:
            log.warning("%s 請求失敗：%s（第 %d 次）", host_key, exc, attempt)

        if attempt < MAX_RETRY:
            time.sleep(BACKOFF_BASE * attempt)
    return None
