"""김프 알림 서버 (FastAPI).

- 24시간 시세 감시 → 설정한 조건 넘으면 텔레그램 푸시 (앱 꺼도 옴)
- 웹앱에 실시간 시세 제공(/api/prices) + 설정 저장(/api/settings)
- 웹앱(static/index.html)도 이 서버가 서빙

실행:  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import os
import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import market

SETTINGS_FILE = os.environ.get("SETTINGS_FILE", "settings.json")
POLL = int(os.environ.get("POLL_INTERVAL", "10"))   # 감시 주기 (초)
KST = timezone(timedelta(hours=9))
ALERT_REPEAT = int(os.environ.get("ALERT_REPEAT", "1800"))   # 조건 유지 중 재알림 간격(초) = 30분
# 기본은 알림 OFF — 서버가 재시작/재배포로 초기화돼도 스팸이 안 나게. 사용자가 앱에서 켬.
DEFAULTS = {
    "enabled": False, "spread": 3.0, "kimp_high": 0.0, "kimp_low": -1.5,
    # 환율 알림 (원)
    "rate_enabled": False, "rate_high": 1500.0, "rate_low": 1450.0,
    # 금 알림 (KRX 금시장 개장 시간에만 작동)
    "gold_enabled": False, "gold_high": 1.0, "gold_low": -1.0,
}

_state = {"data": None, "updated": 0.0}
_settings = dict(DEFAULTS)
_flags = {"spread": False, "prem": False, "rate": False, "gold": False}   # 조건 '진입'할 때만 알림 (도배 방지)
_last = {"spread": 0.0, "prem": 0.0, "rate": 0.0, "gold": 0.0}            # 마지막 알림 시각 (쿨다운)


def _alert(kind, hit, msg):
    """조건에 '처음 진입'할 때 즉시 1회 + 유지되는 동안 ALERT_REPEAT(30분)마다 재알림.
    조건을 벗어나면 플래그 해제 → 다시 들어올 때 또 즉시 알림."""
    now = time.time()
    if hit:
        if (not _flags[kind]) or (now - _last[kind] >= ALERT_REPEAT):
            _last[kind] = now
            market.send_telegram(msg)
        _flags[kind] = True
    else:
        _flags[kind] = False


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            _settings.update(json.load(f))
    except Exception:
        pass


def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(_settings, f)
    except Exception:
        pass


def _now():
    return datetime.now(KST).strftime("%H:%M:%S")


def check_alerts(d):
    if not _settings.get("enabled"):
        return
    # 1) 거래소 차이
    sp = d.get("spread")
    if sp is not None:
        hit = sp >= float(_settings["spread"])
        up, bi = d.get("upbit") or 0, d.get("bithumb") or 0
        dirn = "업비트 &gt; 빗썸" if up > bi else "빗썸 &gt; 업비트"
        _alert("spread", hit,
               f"🚨 <b>USDT 거래소 차익 {sp:.1f}원</b>\n\n"
               f"업비트: {up:,.0f}원\n빗썸: {bi:,.0f}원\n방향: {dirn}\n⏰ {_now()}")
    # 2) 김치 프리미엄 (상단 위 또는 하단 아래)
    avg = d.get("avg_premium")
    if avg is not None:
        hi = float(_settings["kimp_high"])
        lo = float(_settings["kimp_low"])
        hit = avg >= hi or avg <= lo
        zone = f"▲ {hi}% 위" if avg >= hi else f"▼ {lo}% 아래"
        emoji = "🔴" if avg >= 0 else "🔵"
        _alert("prem", hit,
               f"{emoji} <b>김치 프리미엄 {avg:+.2f}%</b> ({zone})\n\n"
               f"환율: {d['usd_krw']:,.1f}원 ({d['rate_src']})\n"
               f"업비트: {d['upbit_premium']:+.2f}% · 빗썸: {d['bithumb_premium']:+.2f}%\n⏰ {_now()}")

    # 3) 환율 (원-달러) — 설정한 원 이상/이하
    rt = d.get("usd_krw")
    if _settings.get("rate_enabled") and rt is not None:
        rhi = float(_settings["rate_high"])
        rlo = float(_settings["rate_low"])
        hit = rt >= rhi or rt <= rlo
        zone = f"▲ {rhi:,.0f}원 이상" if rt >= rhi else f"▼ {rlo:,.0f}원 이하"
        _alert("rate", hit,
               f"💱 <b>원-달러 환율 {rt:,.1f}원</b> ({zone})\n\n"
               f"출처: {d.get('rate_src')}\n⏰ {_now()}")
    else:
        _flags["rate"] = False

    # 4) 금 프리미엄 (KRX 금시장 개장 시간에만! 마감이면 국내 금값이 멈춰 의미 없음)
    gp = d.get("gold_premium")
    if _settings.get("gold_enabled") and d.get("gold_market_open") and gp is not None:
        ghi = float(_settings["gold_high"])
        glo = float(_settings["gold_low"])
        hit = gp >= ghi or gp <= glo
        zone = f"▲ {ghi}% 위" if gp >= ghi else f"▼ {glo}% 아래"
        emoji = "🟡" if gp >= 0 else "🟢"
        _alert("gold", hit,
               f"{emoji} <b>금 프리미엄 {gp:+.2f}%</b> ({zone})\n\n"
               f"국내 금: {d['gold_domestic']:,.0f}원/g\n"
               f"국제(환산): {d['gold_intl_krw_g']:,.0f}원/g\n⏰ {_now()}")
    else:
        _flags["gold"] = False   # 장 마감이면 리셋 → 다음 개장 때 다시 알림 가능


def monitor():
    # 시작 메시지는 보내지 않음 — 서버가 잠들었다 깨어날 때마다 "시작" 알림이 도배되던 문제 제거.
    # (알림은 오직 설정한 조건이 충족될 때만 옴)
    print("monitor started")
    while True:
        try:
            d = market.fetch_market()
            if d.get("usd_krw") is not None:
                _state["data"] = d
                _state["updated"] = time.time()
                # 서버가 깨어 있을 땐 실시간(10초)으로 알림 판정·발송.
                # 서버가 잠들면 GitHub Actions가 백업으로 대신 쏨(중복 안 되게 서버 warm이면 skip).
                if os.environ.get("SERVER_SIDE_ALERTS", "1") != "0":
                    check_alerts(d)
        except Exception as e:  # noqa: BLE001
            print("monitor error:", e)
        time.sleep(POLL)


@asynccontextmanager
async def lifespan(app):
    load_settings()
    if os.environ.get("DISABLE_MONITOR") != "1":
        threading.Thread(target=monitor, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/prices")
def prices():
    d = _state["data"]
    if d is None or time.time() - _state["updated"] > 60:
        fresh = market.fetch_market()
        if fresh.get("usd_krw") is not None:
            _state["data"] = fresh
            _state["updated"] = time.time()
            d = fresh
        elif d is None:
            d = fresh
    return JSONResponse(d)


@app.get("/api/settings")
def get_settings():
    return _settings


@app.post("/api/settings")
async def post_settings(req: Request):
    body = await req.json()
    changed = False
    for k in ("enabled", "spread", "kimp_high", "kimp_low",
              "rate_enabled", "rate_high", "rate_low",
              "gold_enabled", "gold_high", "gold_low"):
        if k in body and _settings.get(k) != body[k]:
            _settings[k] = body[k]
            changed = True
    if changed:
        save_settings()
        # 값이 실제로 바뀐 경우에만 조건·쿨다운 재평가 (주기적 재전송은 무시 → 도배 방지)
        for k in _flags:
            _flags[k] = False
            _last[k] = 0.0
    return _settings


@app.post("/api/test-alert")
def test_alert():
    return {"ok": market.send_telegram("✅ 테스트: 김프 알림 서버 연결 성공!")}


@app.get("/healthz")
def healthz():
    """가벼운 keep-alive 엔드포인트. UptimeRobot·cron-job.org가 5분마다 여길 치면
    서버가 안 자고 24시간 감시(알림)를 계속함. (Render 무료는 15분 무접속 시 잠듦)"""
    age = int(time.time() - _state["updated"]) if _state["updated"] else None
    return {"ok": True, "monitor_data_age_sec": age, "enabled": _settings.get("enabled")}


# 웹앱 서빙 (/ → static/index.html). /api/* 가 우선.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
