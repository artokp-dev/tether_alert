"""일회성 진단: 국제 금 '선물(GC=F)' vs '현물(spot)' 비교 → 어느 쪽이 goldkimp와 맞나."""
import json
import requests

UA = {"User-Agent": "Mozilla/5.0 (KimchiPremiumTracker)"}
G = 31.1034768


def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=10, **kw)
    r.raise_for_status()
    return r.json()


def yahoo_price(sym):
    j = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d")
    return float(j["chart"]["result"][0]["meta"]["regularMarketPrice"])


def spot_goldprice_org():
    j = get("https://data-asg.goldprice.org/dbXRates/USD")
    return float(j["items"][0]["xauPrice"])


def domestic_krw_g():
    urls = [
        "https://api.stock.naver.com/marketindex/metals/M04020000/prices?page=1&pageSize=1",
        "https://polling.finance.naver.com/api/realtime/marketindex/metals/M04020000",
        "https://m.stock.naver.com/front-api/v1/marketIndex/prices?category=metals&reutersCode=M04020000&page=1&pageSize=1",
    ]
    h = dict(UA); h["Referer"] = "https://m.stock.naver.com/"

    def find(o):
        if isinstance(o, dict):
            for k in ("closePrice", "nowVal", "closeVal", "price", "amount", "value"):
                if o.get(k) not in (None, ""):
                    try:
                        v = float(str(o[k]).replace(",", ""))
                        if 50000 < v < 1000000:
                            return v
                    except Exception:
                        pass
            for v in o.values():
                r = find(v)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r:
                    return r
        return None

    for u in urls:
        try:
            p = find(requests.get(u, headers=h, timeout=10).json())
            if p:
                return p
        except Exception:
            pass
    return None


def main():
    out = {}
    try:
        out["futures_GCF_usd_oz"] = yahoo_price("GC=F")
    except Exception as e:
        out["futures_err"] = str(e)
    try:
        out["spot_yahoo_XAUUSD_usd_oz"] = yahoo_price("XAUUSD=X")
    except Exception as e:
        out["spot_yahoo_err"] = str(e)
    try:
        out["spot_goldprice_org_usd_oz"] = spot_goldprice_org()
    except Exception as e:
        out["spot_gp_err"] = str(e)
    try:
        out["rate_krw"] = yahoo_price("KRW=X")
    except Exception as e:
        out["rate_err"] = str(e)
    out["domestic_krw_g"] = domestic_krw_g()

    dom = out.get("domestic_krw_g")
    rate = out.get("rate_krw")
    for label, key in [("선물 GC=F", "futures_GCF_usd_oz"),
                       ("현물 Yahoo XAU", "spot_yahoo_XAUUSD_usd_oz"),
                       ("현물 goldprice.org", "spot_goldprice_org_usd_oz")]:
        oz = out.get(key)
        if oz and rate and dom:
            intl = oz * rate / G
            prem = (dom / intl - 1) * 100
            out[f"premium__{key}"] = f"{prem:.2f}% (국제환산 {intl:,.0f}원/g)"

    print("GOLD_DIAG_JSON_START")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("GOLD_DIAG_JSON_END")


if __name__ == "__main__":
    main()
