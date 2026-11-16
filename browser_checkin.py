import requests
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

import checkin


def submit_browser(cookie, user_agent):
    cookies = []
    for part in cookie.split(";"):
        if not part.strip():
            continue
        name, separator, value = part.strip().partition("=")
        if not separator or not name:
            raise checkin.CheckinError("COOKIE 中存在无效的 Cookie 项。")
        cookies.append({"name": name, "value": value, "url": "https://glados.cloud"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=user_agent, locale="en-US")
            context.add_cookies(cookies)
            status = context.request.get(checkin.STATUS_URL, timeout=30000)
            if not status.ok:
                raise checkin.CheckinError(f"浏览器登录状态查询失败（HTTP {status.status}）。")
            data = status.json()
            if not isinstance(data, dict):
                raise checkin.CheckinError("浏览器登录状态响应格式异常。")
            if data.get("code") != 0:
                raise checkin.CheckinError(checkin.failure_message(data))

            page = context.new_page()
            page.goto(checkin.REFERER, wait_until="domcontentloaded", timeout=60000)
            # 由官网加载验证组件并提交本次签到，验证结果由服务端判定。
            with page.expect_response(
                lambda response: response.url == checkin.CHECKIN_URL
                and response.request.method == "POST",
                timeout=120000,
            ) as pending:
                page.get_by_role("button", name="Checkin", exact=True).click(timeout=30000)
            response = pending.value
            if not response.ok:
                raise checkin.CheckinError(f"浏览器签到请求失败（HTTP {response.status}）。")
            result = response.json()
            if not isinstance(result, dict):
                raise checkin.CheckinError("浏览器签到响应格式异常。")
            return result
        finally:
            browser.close()


def start_browser():
    try:
        config = checkin.load_config()
    except ValueError as error:
        print(f"签到失败：{error}")
        return False
    cookie = checkin.setting("COOKIE", config)
    user_agent = checkin.setting("USER_AGENT", config) or checkin.DEFAULT_USER_AGENT
    serve = checkin.setting("SERVE", config, "off").lower()
    sckey = checkin.setting("SCKEY", config)
    try:
        if not cookie:
            raise checkin.CheckinError("未配置 COOKIE。")
        result = submit_browser(cookie, user_agent)
    except checkin.CheckinError as error:
        message = f"签到失败：{error}"
    except (BrowserError, ValueError) as error:
        message = f"浏览器签到失败：{type(error).__name__}，请检查页面加载或是否需要人工验证。"
    else:
        headers = checkin.request_headers(cookie, user_agent=user_agent)
        with requests.Session() as session:
            return checkin.report_result(session, headers, result, serve, sckey)
    print(message)
    checkin.notify(serve, sckey, "GLaDOS 签到失败", message)
    return False


if __name__ == "__main__":
    raise SystemExit(0 if start_browser() else 1)
