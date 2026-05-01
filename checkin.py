import requests, json, os

# server酱开关，填off不开启(默认)，填on同时开启cookie失效通知和签到成功通知
sever = os.getenv("SERVE", "on")
# 填写server酱sckey,不开启server酱则不用填
sckey = os.getenv("SCKEY", "SCT344150TXvYz8GLA511CDTWuQMX9hqD4")
# 填入glados账号对应cookie
cookie = os.getenv("COOKIE", "koa:sess=eyJ1c2VySWQiOjMxNDczNiwiX2V4cGlyZSI6MTc5NDY2Njg0NTMzNiwiX21heEFnZSI6MjU5MjAwMDAwMDB9; koa:sess.sig=vSNZgWI95DXAM-P67HiZacow0BE; __stripe_mid=209ed6d1-af7f-4073-81e0-a4b1e037533fa2e886; __stripe_sid=7eb0896f-0bce-4af7-b849-3c8bd445d30e1919f2")


def start():
    url = "https://glados.cloud/api/user/checkin"
    url2 = "https://glados.cloud/api/user/status"
    referer = 'https://glados.cloud/console/checkin'
    checkin = requests.post(url, headers={'cookie': cookie, 'referer': referer})
    state = requests.get(url2, headers={'cookie': cookie, 'referer': referer})

    if 'message' in checkin.text:
        mess = checkin.json()['message']
        time = state.json()['data']['leftDays']
        time = time.split('.')[0]
        # print(time)
        if sever == 'on':
            content = mess + '，you have ' + time + ' days left'
            requests.get('https://sctapi.ftqq.com/' + sckey + '.send?title=glados自动签到&desp='+content)
    else:
        requests.get('https://sctapi.ftqq.com/' + sckey + '.send?title=glados自动签到&desp=cookie过期')


def main_handler(event, context):
    return start()


if __name__ == '__main__':
    start()

