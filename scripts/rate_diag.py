"""일회성 진단: 라이브 서버 환율이 멈췄는지 + 소스별 실제값/갱신시각 비교."""
import json, time, urllib.request
UA = {"User-Agent": "Mozilla/5.0 (KimchiPremiumTracker)"}
def get(u, t=20, h=None):
    r = urllib.request.Request(u, headers=h or UA)
    with urllib.request.urlopen(r, timeout=t) as x:
        return json.loads(x.read().decode())
def src(name, fn):
    try: print(f"  {name}: {fn()}")
    except Exception as e: print(f"  {name}: ERR {e}")
def yahoo(host):
    m = get(f"https://{host}/v8/finance/chart/KRW=X?interval=1m&range=1d")["chart"]["result"][0]["meta"]
    age = int(time.time() - m.get("regularMarketTime", 0))
    return f"{m.get('regularMarketPrice')}  (가격시각 {age}초 전)"
print("=== 소스 직접 조회 (GitHub 러너) ===")
src("yahoo query1", lambda: yahoo("query1.finance.yahoo.com"))
src("yahoo query2", lambda: yahoo("query2.finance.yahoo.com"))
src("dunamu(하나은행)", lambda: (lambda d: f"{d[0]['basePrice']} ({d[0].get('date')} {d[0].get('time')})")(get("https://quotation-api-cdn.dunamu.com/v1/forex/recent?codes=FRX.KRWUSD")))
src("naver FX", lambda: json.dumps(get("https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode=FX_USDKRW", h={**UA, "Referer": "https://m.stock.naver.com/"}), ensure_ascii=False)[:300])
print("=== 라이브 서버 /api/prices (70초 간격 4회, 서버 환율캐시 180초) ===")
for i in range(4):
    try:
        d = get("https://tether-alert.onrender.com/api/prices", t=90)
        print(f"  #{i} usd_krw={d.get('usd_krw')} src={d.get('rate_src')} errors={d.get('errors')}")
    except Exception as e:
        print(f"  #{i} ERR {e}")
    if i < 3: time.sleep(70)
try:
    print("healthz:", get("https://tether-alert.onrender.com/healthz", t=30))
except Exception as e:
    print("healthz ERR", e)
