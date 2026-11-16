import hashlib
import json
import math
import os
import time
from pathlib import Path

import requests


CHECKIN_URL = "https://glados.cloud/api/user/checkin"
STATUS_URL = "https://glados.cloud/api/user/status"
POINTS_URL = "https://glados.cloud/api/user/points"
CHALLENGE_URL = CHECKIN_URL + "/challenge"
REFERER = "https://glados.cloud/console/checkin"
TIMEOUT = 20
CONFIG_FILE = Path(__file__).with_name("config.json")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CHALLENGE_DELAY = 2.7


class CheckinError(ValueError):
    """可安全输出的签到验证错误。"""


def request_headers(cookie, content_type=False, user_agent=DEFAULT_USER_AGENT):
    headers = {
        "accept": "application/json, text/plain, */*",
        "cookie": cookie,
        "origin": "https://glados.cloud",
        "referer": REFERER,
        "user-agent": user_agent,
    }
    if content_type:
        headers["content-type"] = "application/json;charset=UTF-8"
    return headers


def integer_part(value):
    return str(value).split(".", 1)[0] if value is not None else "未知"


def load_config(path=CONFIG_FILE):
    try:
        with path.open(encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 {path.name}：{error}") from error
    if not isinstance(config, dict):
        raise ValueError(f"无法读取 {path.name}：根节点必须是对象")
    return config


def setting(name, config, default=""):
    value = os.getenv(name)
    if value is None:
        value = config.get(name, default)
    return "" if value is None else str(value).strip()


def notify(enabled, sckey, title, description):
    if enabled != "on" or not sckey:
        return
    try:
        result = read_json(requests.post(
            f"https://sctapi.ftqq.com/{sckey}.send",
            data={"title": title, "desp": description},
            timeout=TIMEOUT,
        ))
        if result.get("code") != 0:
            print("通知失败：Server 酱拒绝推送。")
    except (requests.RequestException, ValueError) as error:
        # 请求异常可能包含带密钥的 URL，只输出异常类型。
        print(f"通知失败：{type(error).__name__}")


def read_json(response):
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("接口返回不是 JSON 对象")
    return data


def failure_message(result):
    if result.get("reason") == "turnstile":
        return "服务端要求 Cloudflare Turnstile 验证，请配置 TWOCAPTCHA_API_KEY，或在官网完成验证。"
    if result.get("reason") == "device-mismatch":
        return "设备不匹配，请将 USER_AGENT 设置为创建此登录会话的浏览器 User-Agent。"
    if result.get("code") == -2:
        return "会话失效或没有权限，请重新登录后更新 COOKIE。"
    if "automated check-in detected" in str(result.get("message", "")).lower():
        return "服务端拒绝自动签到，请核对登录浏览器的 USER_AGENT。"
    code = result.get("code")
    detail = f"（code={code}）" if type(code) is int else ""
    return f"服务端未确认签到成功{detail}。"


def checkin_result(result):
    if (
        type(result.get("code")) is not int
        or result.get("reason") == "device-mismatch"
        or "automated check-in detected" in str(result.get("message", "")).lower()
    ):
        return False
    if result.get("code") == 0:
        return True
    message = str(result.get("message", "")).strip().lower()
    return result.get("code") == 1 and (
        result.get("repeated") is True
        or message.startswith("checkin repeats! please try tomorrow")
        or message.startswith("today's observation logged")
    )


def solver_request(method, payload, timeout):
    try:
        result = read_json(requests.post(
            f"https://api.2captcha.com/{method}", json=payload, timeout=timeout,
        ))
    except (requests.RequestException, ValueError) as error:
        raise CheckinError(f"2Captcha 请求失败：{type(error).__name__}。") from None
    if type(result.get("errorId")) is not int or result["errorId"] != 0:
        code = result.get("errorCode")
        if (
            not isinstance(code, str) or not code.startswith("ERROR_")
            or len(code) > 80 or not code.replace("_", "").isalnum()
        ):
            code = "UNKNOWN_ERROR"
        raise CheckinError(f"2Captcha 求解失败（{code}）。")
    return result


def solve_turnstile(api_key, sitekey, nonce, expires_at):
    deadline = min(time.monotonic() + 180, expires_at - 5)
    remaining = deadline - time.monotonic()
    if remaining <= 5:
        raise CheckinError("签到 challenge 剩余时间不足，未创建求解任务。")
    task = solver_request("createTask", {
        "clientKey": api_key,
        "task": {
            "type": "TurnstileTaskProxyless",
            "websiteURL": REFERER,
            "websiteKey": sitekey,
            "action": "checkin",
            "data": nonce,
        },
    }, min(TIMEOUT, remaining))
    task_id = task.get("taskId")
    if type(task_id) is not int or task_id <= 0:
        raise CheckinError("2Captcha 未返回有效任务编号。")
    while deadline - time.monotonic() > 5:
        time.sleep(5)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = solver_request("getTaskResult", {
            "clientKey": api_key, "taskId": task_id,
        }, min(TIMEOUT, remaining))
        if result.get("status") == "processing":
            continue
        solution = result.get("solution")
        if result.get("status") != "ready" or not isinstance(solution, dict):
            raise CheckinError("2Captcha 求解结果格式异常。")
        token = solution.get("token")
        if not isinstance(token, str) or not 0 < len(token) <= 2048:
            raise CheckinError("2Captcha 未返回有效验证令牌。")
        if time.monotonic() >= deadline:
            break
        print("2Captcha 已返回本次验证令牌。")
        return token
    raise CheckinError("2Captcha 求解超时，本次未提交带验证令牌的签到请求。")


def submit_checkin(session, headers, solver_key=""):
    challenge = read_json(session.get(CHALLENGE_URL, headers=headers, timeout=TIMEOUT))
    if type(challenge.get("code")) is not int or challenge["code"] != 0:
        raise CheckinError(failure_message(challenge))
    nonce = challenge.get("nonce")
    ttl = challenge.get("ttl", 300000)
    if (
        not isinstance(nonce, str) or not 0 < len(nonce) <= 4096
        or type(ttl) not in (int, float)
        or (type(ttl) is float and not math.isfinite(ttl))
        or ttl <= CHALLENGE_DELAY * 1000
    ):
        raise CheckinError("签到 challenge 无效或已过期。")
    received_at = time.monotonic()
    proof = hashlib.sha256((nonce + ".glados-observe-v1").encode("utf-8")).hexdigest()
    time.sleep(CHALLENGE_DELAY)
    payload = {"token": "glados.cloud", "nonce": nonce, "proof": proof}
    if solver_key:
        sitekey = challenge.get("turnstile")
        if not isinstance(sitekey, str) or not 0 < len(sitekey) <= 256:
            raise CheckinError("签到 challenge 未提供有效的 Turnstile sitekey。")
        payload["turnstile"] = solve_turnstile(solver_key, sitekey, nonce, received_at + ttl / 1000)
        payload["tsState"] = "ok"
    if (time.monotonic() - received_at) * 1000 >= ttl:
        raise CheckinError("签到 challenge 已过期，请重新运行。")
    return read_json(session.post(
        CHECKIN_URL,
        headers={**headers, "content-type": "application/json;charset=UTF-8"},
        json=payload,
        timeout=TIMEOUT,
    ))


def start(session=requests):
    try:
        config = load_config()
    except ValueError as error:
        print(f"签到失败：{error}")
        return False

    cookie = setting("COOKIE", config)
    serve = setting("SERVE", config, "off").lower()
    sckey = setting("SCKEY", config)
    user_agent = setting("USER_AGENT", config) or DEFAULT_USER_AGENT
    solver_key = setting("TWOCAPTCHA_API_KEY", config)

    if not cookie:
        print("签到失败：未配置 COOKIE Secret。")
        notify(serve, sckey, "GLaDOS 签到失败", "未配置 COOKIE Secret。")
        return False

    try:
        headers = request_headers(cookie, user_agent=user_agent)
        checkin = submit_checkin(session, headers)
        if checkin.get("reason") == "turnstile" and solver_key:
            print("服务端要求 Turnstile 验证，使用 2Captcha 求解一次。")
            # 已使用的 nonce 不再复用，每次运行至多创建一个付费求解任务。
            checkin = submit_checkin(session, headers, solver_key=solver_key)
    except (requests.RequestException, UnicodeError) as error:
        message = f"GLaDOS 接口请求失败：{type(error).__name__}，今日签到状态未知。"
        print(message)
        notify(serve, sckey, "GLaDOS 签到失败", message)
        return False
    except CheckinError as error:
        message = f"签到失败：{error}"
        print(message)
        notify(serve, sckey, "GLaDOS 签到失败", message)
        return False
    except ValueError:
        message = "无法完成签到验证，请检查会话及服务端接口是否变更。"
        print(message)
        notify(serve, sckey, "GLaDOS 签到失败", message)
        return False

    return report_result(session, headers, checkin, serve, sckey)


def report_result(session, headers, checkin, serve, sckey):
    if not checkin_result(checkin):
        message = failure_message(checkin)
        print(f"签到失败：{message}")
        notify(serve, sckey, "GLaDOS 签到失败", message)
        return False

    account = {}
    try:
        status = read_json(
            session.get(STATUS_URL, headers=headers, timeout=TIMEOUT)
        )
        if isinstance(status.get("data"), dict):
            account = status["data"]
        else:
            print("账户信息查询失败，签到已确认。")
    except (requests.RequestException, ValueError) as error:
        print(f"账户信息查询失败：{type(error).__name__}，签到已确认。")

    repeated = checkin.get("repeated") is True or checkin.get("code") == 1
    message = "今日已签到" if repeated else "签到成功"
    items = checkin.get("list")
    balance = None
    if isinstance(items, list) and items and isinstance(items[0], dict):
        balance = items[0].get("balance")
    if balance is None:
        try:
            points = read_json(session.get(POINTS_URL, headers=headers, timeout=TIMEOUT))
            if points.get("code") == 0 and points.get("points") is not None:
                balance = points["points"]
            else:
                print("积分查询失败，签到已确认。")
        except (requests.RequestException, ValueError) as error:
            print(f"积分查询失败：{type(error).__name__}，签到已确认。")
    content = (
        f"{message}，you have {integer_part(account.get('leftDays'))} days left "
        f"and {integer_part(balance)} points."
    )
    print(content)
    notify(serve, sckey, "GLaDOS 自动签到", content)
    return True


def main_handler(event, context):
    return start()


if __name__ == "__main__":
    with requests.Session() as session:
        raise SystemExit(0 if start(session) else 1)

