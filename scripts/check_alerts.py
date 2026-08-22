"""GitHub Actions(상시 가동)에서 실행되는 '알림 엔진'.

왜 이렇게 하나:
- 예전엔 Render 서버가 켜져 있을 때만 알림을 보냈다. 무료 서버는 15분 무접속이면
  잠들고, 봇 커밋마다 재배포돼 설정이 초기화됐다 → 앱을 열어야만 알림이 오는 문제.
- 이제 GitHub 스케줄러(잠들지 않음)가 data.json을 받고 → 이 스크립트가 조건을 판정 →
  텔레그램으로 직접 발송한다. 서버가 자든 말든, 앱을 열든 말든 알림이 온다.

- 설정(임계값)은 리포지토리의 alert_config.json이 '기준'.
  매 실행 때 Render /api/settings 를 가져와 '기본값이 아닌'(=앱에서 사용자가 바꾼) 값이면
  alert_config.json 을 갱신한다. 잠들었다 깨서 초기화된 값(전부 기본값)은 무시 → 설정이 안 날아감.
- 도배 방지: '조건에 새로 진입할 때'만(엣지) + 같은 종류 10분 쿨다운. 상태는 alert_state.json에 보존.
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
DATA_FILE = "data.json"
CONFIG_FILE = "alert_config.json"
STATE_FILE = "alert_state.json"
REPEAT = int(os.environ.get("ALERT_REPEAT", "1800"))      # 조건 유지 중 재알림 간격(초)=30분
DRY_RUN = os.environ.get("DRY_RUN") == "1"                 # 테스트: 실제 발송 안 함
RENDER_BASE = os.environ.get("RENDER_BASE", "https://tether-alert.onrender.com")
RENDER_SETTINGS_URL = RENDER_BASE + "/api/settings"
RENDER_HEALTH_URL = RENDER_BASE + "/healthz"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8643580443:AAGe6kgVvKcSr8Wtiv8dumZrXVZDlBiwrl4")
CHAT_ID = os.environ.get("CHAT_ID", "1772649599")

DEFAULTS = {
    "enabled": False, "spread": 3.0, "kimp_high": 0.0, "kimp_low": -1.5,
    "rate_enabled": False, "rate_high": 1500.0, "rate_low": 1450.0,
    "gold_enabled": False, "gold_high": 1.0, "gold_low": -1.0,
}
_KEYS = list(DEFAULTS)


def _load(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(fallback))


def _save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _now():
    return datetime.now(KST).strftime("%H:%M:%S")


def server_is_warm():
    """서버가 '이미 깨어 있는지' 빠르게 확인(짧은 타임아웃).
    깨어 있으면 서버가 10초마다 실시간 알림을 담당하므로 Action은 발송을 건너뜀(중복 방지).
    자고 있으면(콜드스타트=응답 느림/실패) Action이 백업으로 대신 쏨."""
    try:
        req = urllib.request.Request(RENDER_HEALTH_URL, headers={"User-Agent": "kimp-alert"})
        with urllib.request.urlopen(req, timeout=5) as r:   # warm이면 1초 내 응답
            j = json.loads(r.read().decode())
        # 서버 감시 데이터가 최근(2분 내)이면 확실히 살아서 감시 중
        age = j.get("monitor_data_age_sec")
        return age is None or age < 120
    except Exception:
        return False   # 응답 없음/느림 = 자는 중 → Action이 백업 발송


def fetch_render_settings():
    """Render에 저장된 사용자 설정을 가져옴(서버가 자고 있으면 깨우며 최대 70초 대기)."""
    try:
        req = urllib.request.Request(RENDER_SETTINGS_URL, headers={"User-Agent": "kimp-alert"})
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print("  settings fetch failed:", e)
        return None


def send_telegram(msg):
    if DRY_RUN:
        print("  [DRY_RUN] would send:\n   " + msg.replace("\n", "\n   "))
        return True
    try:
        body = urllib.parse.urlencode(
            {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=body)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        print("  telegram failed:", e)
        return False


def sync_config():
    """alert_config.json 을 기준으로 하되, Render가 '사용자가 바꾼(기본값 아님)' 설정을
    갖고 있으면 그걸로 갱신. 잠들었다 깨서 초기화된(전부 기본값) 설정은 무시."""
    config = _load(CONFIG_FILE, DEFAULTS)
    fetched = fetch_render_settings()
    if fetched:
        picked = {k: fetched[k] for k in _KEYS if k in fetched}
        is_reset = all(picked.get(k, DEFAULTS[k]) == DEFAULTS[k] for k in _KEYS)
        if picked and not is_reset:
            config.update(picked)
            print("  → Render 설정 채택(사용자 지정값)")
        else:
            print("  → Render 초기화/미설정 상태 → 기존 config 유지")
    _save(CONFIG_FILE, config)
    return config


def main():
    d = _load(DATA_FILE, {})
    state = _load(STATE_FILE, {"flags": {}, "last": {}})
    flags, last = state.get("flags", {}), state.get("last", {})
    print("data:", {k: d.get(k) for k in
          ("usd_krw", "avg_premium", "spread", "gold_premium", "gold_market_open")})

    # 서버가 깨어 있으면(=실시간 감시 중) 알림은 서버가 담당 → Action은 발송 skip(중복 방지).
    if server_is_warm():
        sync_config()   # 서버가 살아있으니 설정만 최신으로 동기화(다음 백업 대비)
        print("  서버 warm → 실시간 알림은 서버 담당, Action 발송 건너뜀")
        _save(STATE_FILE, state)
        return

    # 서버가 잠들었음 → Action이 백업으로 발송 (커밋된 마지막 설정 사용)
    config = _load(CONFIG_FILE, DEFAULTS)
    print("  서버 sleep → Action 백업 발송 모드 · config:", config)

    def alert(kind, hit, msg):
        t = time.time()
        if hit:
            if (not flags.get(kind)) or (t - last.get(kind, 0) >= REPEAT):
                last[kind] = t
                ok = send_telegram(msg)
                print(f"  fired [{kind}] sent={ok}")
            flags[kind] = True
        else:
            flags[kind] = False

    if config.get("enabled"):
        # 1) 거래소 차이(스프레드)
        sp = d.get("spread")
        if sp is not None:
            up, bi = d.get("upbit") or 0, d.get("bithumb") or 0
            dirn = "업비트 &gt; 빗썸" if up > bi else "빗썸 &gt; 업비트"
            alert("spread", sp >= float(config["spread"]),
                  f"🚨 <b>USDT 거래소 차익 {sp:.1f}원</b>\n\n"
                  f"업비트: {up:,.0f}원\n빗썸: {bi:,.0f}원\n방향: {dirn}\n⏰ {_now()}")
        # 2) 김치 프리미엄 (avg_premium 없으면 두 프리미엄 평균으로 계산)
        avg = d.get("avg_premium")
        if avg is None:
            _ps = [p for p in (d.get("upbit_premium"), d.get("bithumb_premium")) if p is not None]
            avg = round(sum(_ps) / len(_ps), 2) if _ps else None
        if avg is not None:
            hi, lo = float(config["kimp_high"]), float(config["kimp_low"])
            zone = f"▲ {hi}% 위" if avg >= hi else f"▼ {lo}% 아래"
            emoji = "🔴" if avg >= 0 else "🔵"
            alert("prem", avg >= hi or avg <= lo,
                  f"{emoji} <b>김치 프리미엄 {avg:+.2f}%</b> ({zone})\n\n"
                  f"환율: {d.get('usd_krw'):,.1f}원 ({d.get('rate_src')})\n"
                  f"업비트: {d.get('upbit_premium'):+.2f}% · 빗썸: {d.get('bithumb_premium'):+.2f}%\n⏰ {_now()}")
        # 3) 환율
        rt = d.get("usd_krw")
        if config.get("rate_enabled") and rt is not None:
            rhi, rlo = float(config["rate_high"]), float(config["rate_low"])
            zone = f"▲ {rhi:,.0f}원 이상" if rt >= rhi else f"▼ {rlo:,.0f}원 이하"
            alert("rate", rt >= rhi or rt <= rlo,
                  f"💱 <b>원-달러 환율 {rt:,.1f}원</b> ({zone})\n\n"
                  f"출처: {d.get('rate_src')}\n⏰ {_now()}")
        else:
            flags["rate"] = False
        # 4) 금 프리미엄 (KRX 개장 시간에만)
        gp = d.get("gold_premium")
        if config.get("gold_enabled") and d.get("gold_market_open") and gp is not None:
            ghi, glo = float(config["gold_high"]), float(config["gold_low"])
            zone = f"▲ {ghi}% 위" if gp >= ghi else f"▼ {glo}% 아래"
            emoji = "🟡" if gp >= 0 else "🟢"
            alert("gold", gp >= ghi or gp <= glo,
                  f"{emoji} <b>금 프리미엄 {gp:+.2f}%</b> ({zone})\n\n"
                  f"국내 금: {d.get('gold_domestic'):,.0f}원/g\n"
                  f"국제(환산): {d.get('gold_intl_krw_g'):,.0f}원/g\n⏰ {_now()}")
        else:
            flags["gold"] = False
    else:
        print("  알림 마스터 OFF → 판정 안 함")

    print(f"(dry_run={DRY_RUN})")
    state["flags"], state["last"] = flags, last
    _save(STATE_FILE, state)


if __name__ == "__main__":
    main()
