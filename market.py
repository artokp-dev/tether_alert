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

# 24시간 국제 forex 환율 (무료 API 키 필요) — 평일 밤·새벽에도 움직임
FOREX_API_KEY = os.environ.get("FOREX_API_KEY", "")
TWELVE = "https://api.twelvedata.com/price?symbol=USD/KRW&apikey={key}"
RATE_TTL = int(os.environ.get("RATE_TTL", "180"))   # 환율 캐시(초). 무료 API 한도 보호
_rate_cache = {"val": None, "src": None, "ts": 0.0}

# 금(Gold)
G_PER_OZT = 31.1034768   # 1 트로이온스 = 31.1034768 g
YAHOO_GOLD = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d"  # 국제 금 (USD/oz)
# 네이버가 제공하는 국내 금(KRX 금현물, 원/g)
NAVER_GOLD = ("https://m.stock.naver.com/front-api/v1/marketIndex/prices"
              "?page=1&category=metals&reutersCode=M04020000&pageSize=1")


def _get(url):
    r = requests.get(url, headers=UA, timeout=8)
    r.raise_for_status()
    return r.json()


def _to_float(x):
    return float(str(x).replace(",", "").strip())


def get_intl_gold_usd_oz():
    """국제 금 시세 (USD / 트로이온스) — 야후 금 선물 GC=F."""
    y = _get(YAHOO_GOLD)
    return float(y["chart"]["result"][0]["meta"]["regularMarketPrice"])


NAVER_GOLD_URLS = [
    "https://api.stock.naver.com/marketindex/metals/M04020000/prices?page=1&pageSize=1",
    "https://api.stock.naver.com/marketindex/metals/M04020000",
    "https://m.stock.naver.com/front-api/v1/marketIndex/prices?category=metals&reutersCode=M04020000&page=1&pageSize=1",
    "https://polling.finance.naver.com/api/realtime/marketindex/metals/M04020000",
]
_GOLD_KEYS = ("closePrice", "nowVal", "closeVal", "closePriceKrw", "price", "amount", "value")


def _find_gold_price(obj, keys=_GOLD_KEYS):
    """JSON 안에서 원/g 가격을 재귀로 찾음 (상식 범위 5만~100만 원)."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                try:
                    v = _to_float(obj[k])
                    if 50000 < v < 1000000:
                        return v
                except Exception:
                    pass
        for v in obj.values():
            r = _find_gold_price(v, keys)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_gold_price(v, keys)
            if r:
                return r
    return None


def get_domestic_gold_krw_g():
    """국내 금 시세 (원 / g) — 네이버가 제공하는 KRX 금현물 (여러 엔드포인트 시도)."""
    headers = dict(UA)
    headers["Referer"] = "https://m.stock.naver.com/"
    last = None
    for u in NAVER_GOLD_URLS:
        try:
            r = requests.get(u, headers=headers, timeout=8)
            r.raise_for_status()
            p = _find_gold_price(r.json())
            if p:
                return p
        except Exception as e:  # noqa: BLE001
            last = e
    raise last or ValueError("no domestic gold endpoint returned a usable price")


def get_upbit():
    return float(_get(UPBIT)[0]["trade_price"])


def get_bithumb():
    return float(_get(BITHUMB)["data"]["closing_price"])


def _fetch_rate():
    # 1순위: 24시간 국제 forex (Twelve Data) — 키가 있을 때. 저녁·새벽에도 갱신
    if FOREX_API_KEY:
        try:
            j = _get(TWELVE.format(key=FOREX_API_KEY))
            p = j.get("price")
            if p:
                return float(p), "24h실시간"
        except Exception:
            pass
    # 2순위: 야후 시장환율 (한국 장중 위주 → 저녁엔 잘 안 움직임)
    try:
        y = _get(YAHOO)
        p = y["chart"]["result"][0]["meta"].get("regularMarketPrice")
        if p:
            return float(p), "시장환율"
    except Exception:
        pass
    # 3순위: 하나은행 고시환율 (은행 영업시간만)
    d = _get(DUNAMU)
    return float(d[0]["basePrice"]), "하나은행"


def get_rate():
    """환율 (RATE_TTL초 캐시 — 가격은 10초마다여도 환율 API는 아껴 호출)."""
    now = time.time()
    if _rate_cache["val"] and now - _rate_cache["ts"] < RATE_TTL:
        return _rate_cache["val"], _rate_cache["src"]
    try:
        val, src = _fetch_rate()
        _rate_cache.update(val=val, src=src, ts=now)
        return val, src
    except Exception:
        if _rate_cache["val"]:   # 조회 실패 시 마지막 값 유지
            return _rate_cache["val"], _rate_cache["src"]
        raise


def _prem(p, rate):
    return round((p / rate - 1) * 100, 2) if (p and rate) else None


def fetch_market():
    out = {
        "upbit": None, "bithumb": None, "usd_krw": None, "rate_src": None,
        "upbit_premium": None, "bithumb_premium": None, "avg_premium": None,
        "spread": None,
        # 금
        "gold_domestic": None, "gold_intl_usd_oz": None,
        "gold_intl_krw_g": None, "gold_premium": None,
        "updated": int(time.time() * 1000), "errors": [],
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

    # --- 금 김치 프리미엄 (실패해도 나머지는 유지) ---
    try:
        out["gold_intl_usd_oz"] = get_intl_gold_usd_oz()
    except Exception as e:
        out["errors"].append(f"gold_intl: {e}")
    try:
        out["gold_domestic"] = get_domestic_gold_krw_g()
    except Exception as e:
        out["errors"].append(f"gold_domestic: {e}")
    if out["gold_intl_usd_oz"] and rate:
        out["gold_intl_krw_g"] = round(out["gold_intl_usd_oz"] * rate / G_PER_OZT, 1)
    if out["gold_domestic"] and out["gold_intl_krw_g"]:
        out["gold_premium"] = round((out["gold_domestic"] / out["gold_intl_krw_g"] - 1) * 100, 2)

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
