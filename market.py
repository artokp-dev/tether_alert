"""시세 수집 + 텔레그램 (서버에서 사용). 서버가 호출하므로 CORS 없음."""
import os
import time
import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8643580443:AAGe6kgVvKcSr8Wtiv8dumZrXVZDlBiwrl4")
CHAT_ID = os.environ.get("CHAT_ID", "1772649599")

UA = {"User-Agent": "Mozilla/5.0 (KimchiPremiumTracker)"}
UPBIT = "https://api.upbit.com/v1/ticker?markets=KRW-USDT"
BITHUMB = "https://api.bithumb.com/public/ticker/USDT_KRW"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X?interval=1m&range=1d"
DUNAMU = "https://quotation-api-cdn.dunamu.com/v1/forex/recent?codes=FRX.KRWUSD"


def _get(url):
    r = requests.get(url, headers=UA, timeout=8)
    r.raise_for_status()
    return r.json()


def get_upbit():
    return float(_get(UPBIT)[0]["trade_price"])


def get_bithumb():
    return float(_get(BITHUMB)["data"]["closing_price"])


def get_rate():
    # 1순위 24시간 시장환율(야후) → 2순위 하나은행 고시환율(두나무)
    try:
        y = _get(YAHOO)
        p = y["chart"]["result"][0]["meta"].get("regularMarketPrice")
        if p:
            return float(p), "시장환율"
    except Exception:
        pass
    d = _get(DUNAMU)
    return float(d[0]["basePrice"]), "하나은행"


def _prem(p, rate):
    return round((p / rate - 1) * 100, 2) if (p and rate) else None


def fetch_market():
    out = {
        "upbit": None, "bithumb": None, "usd_krw": None, "rate_src": None,
        "upbit_premium": None, "bithumb_premium": None, "avg_premium": None,
        "spread": None, "updated": int(time.time() * 1000), "errors": [],
    }
    try:
        out["upbit"] = get_upbit()
    except Exception as e:
        out["errors"].append(f"upbit: {e}")
    try:
        out["bithumb"] = get_bithumb()
    except Exception as e:
        out["errors"].append(f"bithumb: {e}")
    try:
        out["usd_krw"], out["rate_src"] = get_rate()
    except Exception as e:
        out["errors"].append(f"rate: {e}")

    rate = out["usd_krw"]
    out["upbit_premium"] = _prem(out["upbit"], rate)
    out["bithumb_premium"] = _prem(out["bithumb"], rate)
    prems = [p for p in (out["upbit_premium"], out["bithumb_premium"]) if p is not None]
    out["avg_premium"] = round(sum(prems) / len(prems), 2) if prems else None
    if out["upbit"] and out["bithumb"]:
        out["spread"] = round(abs(out["upbit"] - out["bithumb"]), 1)
    return out


def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=8,
        )
        return r.ok
    except Exception:
        return False
