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
DEFAULTS = {"enabled": True, "spread": 3.0, "kimp_high": 0.0, "kimp_low": -1.5}

_state = {"data": None, "updated": 0.0}
_settings = dict(DEFAULTS)
_flags = {"spread": False, "prem": False}   # 조건 '진입'할 때만 알림 (도배 방지)


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
        if hit and not _flags["spread"]:
            up, bi = d["upbit"], d["bithumb"]
            dirn = "업비트 &gt; 빗썸" if up > bi else "빗썸 &gt; 업비트"
            market.send_telegram(
                f"🚨 <b>USDT 거래소 차익 {sp:.1f}원</b>\n\n"
                f"업비트: {up:,.0f}원\n빗썸: {bi:,.0f}원\n방향: {dirn}\n⏰ {_now()}"
            )
        _flags["spread"] = hit
    # 2) 김치 프리미엄 (상단 위 또는 하단 아래)
    avg = d.get("avg_premium")
    if avg is not None:
        hi = float(_settings["kimp_high"])
        lo = float(_settings["kimp_low"])
        hit = avg >= hi or avg <= lo
        if hit and not _flags["prem"]:
            zone = f"▲ {hi}% 위" if avg >= hi else f"▼ {lo}% 아래"
            emoji = "🔴" if avg >= 0 else "🔵"
            market.send_telegram(
                f"{emoji} <b>김치 프리미엄 {avg:+.2f}%</b> ({zone})\n\n"
                f"환율: {d['usd_krw']:,.1f}원 ({d['rate_src']})\n"
                f"업비트: {d['upbit_premium']:+.2f}% · 빗썸: {d['bithumb_premium']:+.2f}%\n⏰ {_now()}"
            )
        _flags["prem"] = hit


def monitor():
    market.send_telegram("✅ 김프 알림 서버 시작! (24시간 감시 중)")
    while True:
        try:
            d = market.fetch_market()
            if d.get("usd_krw") is not None:
                _state["data"] = d
                _state["updated"] = time.time()
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
    for k in ("enabled", "spread", "kimp_high", "kimp_low"):
        if k in body:
            _settings[k] = body[k]
    save_settings()
    _flags["spread"] = False
    _flags["prem"] = False   # 설정 바뀌면 조건 재평가
    return _settings


@app.post("/api/test-alert")
def test_alert():
    return {"ok": market.send_telegram("✅ 테스트: 김프 알림 서버 연결 성공!")}


# 웹앱 서빙 (/ → static/index.html). /api/* 가 우선.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
