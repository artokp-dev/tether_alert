"""GitHub Actions에서 5분마다 실행 → 시세/환율을 서버에서 받아 data.json 저장.

서버(GitHub 러너)가 대신 호출하므로 폰의 CORS/캐시 문제가 원천 차단된다.
"""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (KimchiPremiumTracker)"}


G_PER_OZT = 31.1034768


def get(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _to_float(x):
    return float(str(x).replace(",", "").strip())


def get_intl_gold_usd_oz():
    y = get("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d")
    return float(y["chart"]["result"][0]["meta"]["regularMarketPrice"])


def get_domestic_gold_krw_g():
    url = ("https://m.stock.naver.com/front-api/v1/marketIndex/prices"
           "?page=1&category=metals&reutersCode=M04020000&pageSize=1")
    h = dict(UA); h["Referer"] = "https://m.stock.naver.com/"
    j = get(url, headers=h)
    res = j.get("result", j)
    if isinstance(res, dict):
        res = res.get("prices") or res.get("list") or res.get("datas") or [res]
    item = res[0]
    for k in ("closePrice", "nowVal", "closeVal", "price", "closePriceKrw"):
        v = item.get(k)
        if v not in (None, ""):
            return _to_float(v)
    raise ValueError("gold price field not found")


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
