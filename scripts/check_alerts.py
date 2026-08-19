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
COOLDOWN = int(os.environ.get("ALERT_COOLDOWN", "600"))   # 같은 알림 최소 간격(초)
DRY_RUN = os.environ.get("DRY_RUN") == "1"                 # 테스트: 실제 발송 안 함
RENDER_SETTINGS_URL = os.environ.get(
    "RENDER_SETTINGS_URL", "https://tether-alert.onrender.com/api/settings")

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
    config = sync_config()
    state = _load(STATE_FILE, {"flags": {}, "last": {}})
    flags, last = state.get("flags", {}), state.get("last", {})

    print("data:", {k: d.get(k) for k in
          ("usd_krw", "avg_premium", "spread", "gold_premium", "gold_market_open")})
    print("config:", config)

    to_send = []

    def fire(kind, msg):
        t = time.time()
        if not flags.get(kind) and t - last.get(kind, 0) > COOLDOWN:
            last[kind] = t
            to_send.append((kind, msg))

    if config.get("enabled"):
        # 1) 거래소 차이(스프레드)
        sp = d.get("spread")
        if sp is not None:
            hit = sp >= float(config["spread"])
            if hit:
                up, bi = d.get("upbit"), d.get("bithumb")
                dirn = "업비트 &gt; 빗썸" if (up or 0) > (bi or 0) else "빗썸 &gt; 업비트"
                fire("spread",
                     f"🚨 <b>USDT 거래소 차익 {sp:.1f}원</b>\n\n"
                     f"업비트: {up:,.0f}원\n빗썸: {bi:,.0f}원\n방향: {dirn}\n⏰ {_now()}")
            flags["spread"] = hit
        # 2) 김치 프리미엄 (data.json엔 avg_premium이 없을 수 있어 두 프리미엄 평균으로 계산)
        avg = d.get("avg_premium")
        if avg is None:
            _ps = [p for p in (d.get("upbit_premium"), d.get("bithumb_premium")) if p is not None]
            avg = round(sum(_ps) / len(_ps), 2) if _ps else None
        if avg is not None:
            hi, lo = float(config["kimp_high"]), float(config["kimp_low"])
            hit = avg >= hi or avg <= lo
            if hit:
                zone = f"▲ {hi}% 위" if avg >= hi else f"▼ {lo}% 아래"
                emoji = "🔴" if avg >= 0 else "🔵"
                fire("prem",
                     f"{emoji} <b>김치 프리미엄 {avg:+.2f}%</b> ({zone})\n\n"
                     f"환율: {d.get('usd_krw'):,.1f}원 ({d.get('rate_src')})\n"
                     f"업비트: {d.get('upbit_premium'):+.2f}% · 빗썸: {d.get('bithumb_premium'):+.2f}%\n⏰ {_now()}")
            flags["prem"] = hit
        # 3) 환율
        rt = d.get("usd_krw")
        if config.get("rate_enabled") and rt is not None:
            rhi, rlo = float(config["rate_high"]), float(config["rate_low"])
            hit = rt >= rhi or rt <= rlo
            if hit:
                zone = f"▲ {rhi:,.0f}원 이상" if rt >= rhi else f"▼ {rlo:,.0f}원 이하"
                fire("rate",
                     f"💱 <b>원-달러 환율 {rt:,.1f}원</b> ({zone})\n\n"
                     f"출처: {d.get('rate_src')}\n⏰ {_now()}")
            flags["rate"] = hit
        # 4) 금 프리미엄 (KRX 개장 시간에만)
        gp = d.get("gold_premium")
        if config.get("gold_enabled") and d.get("gold_market_open") and gp is not None:
            ghi, glo = float(config["gold_high"]), float(config["gold_low"])
            hit = gp >= ghi or gp <= glo
            if hit:
                zone = f"▲ {ghi}% 위" if gp >= ghi else f"▼ {glo}% 아래"
                emoji = "🟡" if gp >= 0 else "🟢"
                fire("gold",
                     f"{emoji} <b>금 프리미엄 {gp:+.2f}%</b> ({zone})\n\n"
                     f"국내 금: {d.get('gold_domestic'):,.0f}원/g\n"
                     f"국제(환산): {d.get('gold_intl_krw_g'):,.0f}원/g\n⏰ {_now()}")
            flags["gold"] = hit
        else:
            flags["gold"] = False
    else:
        print("  알림 마스터 OFF → 판정 안 함")

    for kind, msg in to_send:
        ok = send_telegram(msg)
        print(f"  fired [{kind}] sent={ok}")
    print(f"total fired: {len(to_send)} (dry_run={DRY_RUN})")

    state["flags"], state["last"] = flags, last
    _save(STATE_FILE, state)


if __name__ == "__main__":
    main()
