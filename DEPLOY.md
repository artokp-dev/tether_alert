# 서버 배포 가이드 (앱 꺼도 오는 알림)

`server.py`(FastAPI)를 24시간 켜진 서버에 올리면:
- 웹앱에서 설정한 값(스프레드 원, 김프 %위/아래)대로
- 서버가 계속 감시하다가 조건 넘으면 **텔레그램으로 푸시** (앱/폰 꺼도 옴)

배포 후 나오는 **서버 URL**이 새 앱 주소야. 그걸 홈 화면에 추가해서 쓰면 됨.

---

## 방법 A. Render (무료) — 추천

1. https://render.com → **GitHub로 로그인**
2. **New +** → **Web Service** → 저장소 `artokp-dev/tether_alert` 연결
3. `render.yaml`을 자동 감지함. (수동이면: Runtime=Python,
   Build=`pip install -r requirements.txt`,
   Start=`uvicorn server:app --host 0.0.0.0 --port $PORT`, Plan=Free)
4. (선택) **Environment**에 `BOT_TOKEN`, `CHAT_ID` 추가 — 안 넣으면 코드 기본값 사용
5. **Create Web Service** → 몇 분 빌드 → URL 생성
   (예: `https://kimchi-premium-xxxx.onrender.com`)
6. 그 URL 열기 → 웹앱(설정 포함) 뜸 → **텔레그램 테스트** 버튼으로 확인 → 홈 화면 추가

### ⚠️ 무료 티어 "잠자기" 방지 (중요)
Render 무료는 15분간 접속이 없으면 잠들어서 그동안 감시가 멈춥니다.
24시간 유지하려면 무료 핑 서비스로 깨워두세요:
1. https://uptimerobot.com 무료 가입
2. **New Monitor** → Type: **HTTP(s)** → URL에 서버 주소 입력 → 간격 **5분** → 저장
3. 끝. 이제 서버가 안 자고 24시간 감시합니다.

---

## 방법 B. Railway (더 간단, 무료 크레딧 소진 후 월 ~$5)

1. https://railway.app → GitHub 로그인
2. **New Project** → **Deploy from GitHub repo** → `artokp-dev/tether_alert`
3. 자동 감지(Procfile)로 빌드됨
4. **Settings → Networking → Generate Domain** → URL 생성
5. (선택) **Variables**에 `BOT_TOKEN`, `CHAT_ID`
6. URL 열기 → 완료. (Railway는 안 자서 핑 불필요)

---

## 참고
- 설정값은 폰(localStorage)에도 저장돼서, 서버가 재시작돼도 다음 접속 때 자동 복원됩니다.
- 보안: 봇 토큰이 저장소(공개)에 기본값으로 있음. 신경 쓰이면 @BotFather에서 재발급 후
  서버 환경변수(`BOT_TOKEN`)로만 설정하세요.
