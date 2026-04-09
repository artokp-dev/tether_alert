import requests
import time
import os

BOT_TOKEN = os.environ.get('BOT_TOKEN', '8643580443:AAGe6kgVvKcSr8Wtiv8dumZrXVZDlBiwrl4')
CHAT_ID = os.environ.get('CHAT_ID', '1772649599')
SPREAD_THRESHOLD = 3
CHECK_INTERVAL = 30
last_alert_time = 0

def get_upbit_price():
    res = requests.get('https://api.upbit.com/v1/ticker?markets=KRW-USDT', timeout=5)
    return res.json()[0]['trade_price']

def get_bithumb_price():
    res = requests.get('https://api.bithumb.com/public/ticker/USDT_KRW', timeout=5)
    return float(res.json()['data']['closing_price'])

def send_telegram(msg):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    requests.post(url, json={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}, timeout=5)

def main():
    global last_alert_time
    print('테더 차익거래 모니터링 시작...')
    send_telegram('✅ 테더 차익거래 모니터 시작!\n24시간 자동 감시 중입니다.')

    while True:
        try:
            upbit = get_upbit_price()
            bithumb = get_bithumb_price()
            spread = abs(upbit - bithumb)
            now = time.time()
            print(f'업비트: {upbit} | 빗썸: {bithumb} | 스프레드: {spread:.1f}원')

            if spread >= SPREAD_THRESHOLD and now - last_alert_time > 60:
                last_alert_time = now
                higher = '업비트 > 빗썸' if upbit > bithumb else '빗썸 > 업비트'
                msg = (
                    f'🚨 <b>USDT 차익거래 기회!</b>\n\n'
                    f'업비트: {upbit:,}원\n'
                    f'빗썸: {bithumb:,}원\n'
                    f'스프레드: <b>{spread:.1f}원</b>\n'
                    f'방향: {higher}'
                )
                send_telegram(msg)
                print(f'알림 전송: {spread:.1f}원')

        except Exception as e:
            print(f'오류: {e}')

        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    main()
