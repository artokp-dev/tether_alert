"""GitHub Actions에서 5분마다 실행 → 시세/환율을 서버에서 받아 data.json 저장.

서버(GitHub 러너)가 대신 호출하므로 폰의 CORS/캐시 문제가 원천 차단된다.
"""
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta

UA = {"User-Agent": "Mozilla/5.0 (KimchiPremiumTracker)"}
KST = timezone(timedelta(hours=9))


def is_krx_gold_open():
    """KRX 금시장 개장 여부 — 평일 09:00~15:30 (KST)."""
    t = datetime.now(KST)
    if t.weekday() >= 5:
        return False
    hm = t.hour * 60 + t.minute
    return 9 * 60 <= hm <= 15 * 60 + 30


G_PER_OZT = 31.1034768


def get(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _to_float(x):
    return float(str(x).replace(",", "").strip())


def get_intl_gold_usd_oz():
    # 국제 금 현물(spot, XAU) — goldkimp 등 김프 사이트 기준.
    # 실패 시 선물로 튀지 않게 그냥 예외 → main에서 직전 data.json 값을 유지.
    p = float(get("https://api.gold-api.com/price/XAU")["price"])
    if not (500 < p < 20000):
        raise ValueError(f"gold spot out of range: {p}")
    return p


NAVER_GOLD_URLS = [
    "https://api.stock.naver.com/marketindex/metals/M04020000/prices?page=1&pageSize=1",
    "https://api.stock.naver.com/marketindex/metals/M04020000",
    "https://m.stock.naver.com/front-api/v1/marketIndex/prices?category=metals&reutersCode=M04020000&page=1&pageSize=1",
    "https://polling.finance.naver.com/api/realtime/marketindex/metals/M04020000",
]
_GOLD_KEYS = ("closePrice", "nowVal", "closeVal", "closePriceKrw", "price", "amount", "value")


def _find_gold_price(obj, keys):
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
    h = dict(UA); h["Referer"] = "https://m.stock.naver.com/"
    last = None
    for u in NAVER_GOLD_URLS:
        try:
            j = get(u, headers=h)
            p = _find_gold_price(j, _GOLD_KEYS)
            if p:
                return p
        except Exception as e:
            last = e
    raise last or ValueError("no domestic gold endpoint returned a usable price")


def get_upbit():
    return float(get("https://api.upbit.com/v1/ticker?markets=KRW-USDT")[0]["trade_price"])


def get_bithumb():
    return float(get("https://api.bithumb.com/public/ticker/USDT_KRW")["data"]["closing_price"])


def get_rate():
    # 1순위: 24시간 시장환율 (야후 인터뱅크)
    try:
        y = get("https://query1.finance.yahoo.com/v8/finance/chart/KRW=X?interval=1m&range=1d")
        m = y["chart"]["result"][0]["meta"]
        if m.get("regularMarketPrice"):
            return float(m["regularMarketPrice"]), "시장환율"
    except Exception:
        pass
    # 2순위: 하나은행 고시환율 (두나무 제공)
    d = get("https://quotation-api-cdn.dunamu.com/v1/forex/recent?codes=FRX.KRWUSD")
    return float(d[0]["basePrice"]), "하나은행"


def main():
    data = {
        "upbit": None, "bithumb": None, "usd_krw": None, "rate_src": None,
        "upbit_premium": None, "bithumb_premium": None, "spread": None,
        "gold_domestic": None, "gold_intl_usd_oz": None,
        "gold_intl_krw_g": None, "gold_premium": None,
        "gold_market_open": is_krx_gold_open(),
        "updated": int(time.time() * 1000), "errors": [],
    }

    try:
        data["upbit"] = get_upbit()
    except Exception as e:
        data["errors"].append(f"upbit: {e}")
    try:
        data["bithumb"] = get_bithumb()
    except Exception as e:
        data["errors"].append(f"bithumb: {e}")
    try:
        data["usd_krw"], data["rate_src"] = get_rate()
    except Exception as e:
        data["errors"].append(f"rate: {e}")

    def prem(p):
        if p and data["usd_krw"]:
            return round((p / data["usd_krw"] - 1) * 100, 2)
        return None

    data["upbit_premium"] = prem(data["upbit"])
    data["bithumb_premium"] = prem(data["bithumb"])
    if data["upbit"] and data["bithumb"]:
        data["spread"] = round(abs(data["upbit"] - data["bithumb"]), 1)

    # 금 김치 프리미엄
    try:
        data["gold_intl_usd_oz"] = get_intl_gold_usd_oz()
    except Exception as e:
        data["errors"].append(f"gold_intl: {e}")
        # 현물 조회 실패 시 직전 data.json 값 유지 (값이 튀지 않게)
        try:
            with open("data.json", encoding="utf-8") as f:
                data["gold_intl_usd_oz"] = json.load(f).get("gold_intl_usd_oz")
        except Exception:
            pass
    try:
        data["gold_domestic"] = get_domestic_gold_krw_g()
    except Exception as e:
        data["errors"].append(f"gold_domestic: {e}")
    if data["gold_intl_usd_oz"] and data["usd_krw"]:
        data["gold_intl_krw_g"] = round(data["gold_intl_usd_oz"] * data["usd_krw"] / G_PER_OZT, 1)
    if data["gold_domestic"] and data["gold_intl_krw_g"]:
        data["gold_premium"] = round((data["gold_domestic"] / data["gold_intl_krw_g"] - 1) * 100, 2)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
