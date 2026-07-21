/**
 * 김프 / 거래소 차익 텔레그램 알림 (구글 앱스크립트)
 * - 앱을 꺼도 24시간 서버(구글)가 감시해서 텔레그램으로 푸시 알림
 * - 업비트·빗썸 USDT 차이가 기준(원) 이상이면 알림
 * - 김치 프리미엄이 상단(%) 위 또는 하단(%) 아래면 알림
 *
 * 설치: 아래 setup() 을 한 번 실행 → 1분마다 checkAlerts() 자동 실행.
 * (자세한 순서는 apps_script/README.md 참고)
 */

// ===== 설정 (여기 값만 바꾸면 됨) =====
var BOT_TOKEN = 'YOUR_BOT_TOKEN';   // @BotFather 봇 토큰
var CHAT_ID   = 'YOUR_CHAT_ID';     // 내 텔레그램 chat id
var SPREAD_THRESHOLD = 3;           // 업비트·빗썸 차이 (원) 이상이면 알림
var PREMIUM_HIGH = 0;               // 김프 이 값(%) 이상이면 알림
var PREMIUM_LOW  = -1.5;            // 김프 이 값(%) 이하면 알림

// ===== 시세 수집 (서버에서 호출 → CORS 없음) =====
function fetchJson_(url) {
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } });
  return JSON.parse(res.getContentText());
}
function getUpbit_()   { return Number(fetchJson_('https://api.upbit.com/v1/ticker?markets=KRW-USDT')[0].trade_price); }
function getBithumb_() { return Number(fetchJson_('https://api.bithumb.com/public/ticker/USDT_KRW').data.closing_price); }
function getRate_() {
  try {
    var y = fetchJson_('https://query1.finance.yahoo.com/v8/finance/chart/KRW=X?interval=1m&range=1d');
    var p = y.chart.result[0].meta.regularMarketPrice;
    if (p) return { rate: Number(p), src: '시장환율' };
  } catch (e) {}
  var d = fetchJson_('https://quotation-api-cdn.dunamu.com/v1/forex/recent?codes=FRX.KRWUSD');
  return { rate: Number(d[0].basePrice), src: '하나은행' };
}

function won_(n) { return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ','); }

function sendTelegram_(msg) {
  UrlFetchApp.fetch('https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage', {
    method: 'post', muteHttpExceptions: true,
    payload: { chat_id: CHAT_ID, text: msg, parse_mode: 'HTML' }
  });
}

// ===== 1분마다 실행되는 감시 =====
function checkAlerts() {
  var upbit, bithumb, r;
  try { upbit = getUpbit_(); bithumb = getBithumb_(); r = getRate_(); }
  catch (e) { return; }  // 조회 실패한 회차는 조용히 건너뜀
  if (!upbit || !bithumb || !r || !r.rate) return;

  var rate = r.rate;
  var spread = Math.abs(upbit - bithumb);
  var upP = (upbit / rate - 1) * 100;
  var biP = (bithumb / rate - 1) * 100;
  var avg = (upP + biP) / 2;

  var props = PropertiesService.getScriptProperties();
  var time = Utilities.formatDate(new Date(), 'Asia/Seoul', 'HH:mm:ss');

  // 1) 거래소 차이 알림 (조건에 '진입'할 때 1회만 → 도배 방지)
  var spreadHit = spread >= SPREAD_THRESHOLD;
  if (spreadHit && props.getProperty('spreadHit') !== '1') {
    var dir = upbit > bithumb ? '업비트 &gt; 빗썸' : '빗썸 &gt; 업비트';
    sendTelegram_('🚨 <b>USDT 거래소 차익 ' + spread.toFixed(1) + '원</b>\n\n' +
      '업비트: ' + won_(upbit) + '원\n빗썸: ' + won_(bithumb) + '원\n방향: ' + dir + '\n⏰ ' + time);
  }
  props.setProperty('spreadHit', spreadHit ? '1' : '0');

  // 2) 김프 알림 (상단 위 또는 하단 아래로 '진입'할 때 1회만)
  var premHit = (avg >= PREMIUM_HIGH) || (avg <= PREMIUM_LOW);
  if (premHit && props.getProperty('premHit') !== '1') {
    var zone = avg >= PREMIUM_HIGH ? '▲ ' + PREMIUM_HIGH + '% 위' : '▼ ' + PREMIUM_LOW + '% 아래';
    sendTelegram_((avg >= 0 ? '🔴' : '🔵') + ' <b>김치 프리미엄 ' + avg.toFixed(2) + '%</b> (' + zone + ')\n\n' +
      '환율: ' + won_(rate) + '원 (' + r.src + ')\n' +
      '업비트: ' + upP.toFixed(2) + '% · 빗썸: ' + biP.toFixed(2) + '%\n⏰ ' + time);
  }
  props.setProperty('premHit', premHit ? '1' : '0');
}

// ===== 최초 1회만 실행: 1분 자동 트리거 설치 =====
function setup() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('checkAlerts').timeBased().everyMinutes(1).create();
  sendTelegram_('✅ 김프/차익 알림 봇 시작! (1분마다 감시, 앱 꺼도 알림)');
}

// 지금 바로 한 번 테스트로 보내보고 싶을 때 실행
function testNow() {
  sendTelegram_('✅ 테스트: 알림 봇 연결 성공!');
  checkAlerts();
}
