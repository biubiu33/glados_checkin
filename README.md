# GLaDOS 每日签到

支持 GitHub Actions 定时签到和本机 Chrome / Edge 浏览器扩展，提供多账号、多域名探测、积分兑换、结果推送及签到日历。

## 浏览器扩展

1. 下载并解压本仓库。
2. 打开 `chrome://extensions` 或 `edge://extensions`，开启开发者模式。
3. 点击“加载已解压的扩展程序”，选择 `extension` 目录。
4. 在同一浏览器登录 GLaDOS，扩展中添加账号，认证方式选择“浏览器登录态”。
5. 设置签到时段，保存后点击“立即签到”，核对服务端签到记录。

扩展包含以下功能。

- 浏览器登录态及手动 Cookie 多账号，支持 8 个站点。
- 在官网页面点击签到按钮，由网页执行 challenge 和 Turnstile。
- 定时运行、启动补签、随机延迟、每日已签跳过及最多 3 次退避重试。
- 30 天签到日历、账户身份核对、积分兑换、桌面通知和汇总推送。
- Cookie 模式的请求头注入同时限制目标域名和临时标签页。

扩展运行时需要电脑开机、浏览器保持运行。交互式 Turnstile 可能需要手动完成。首次签到的自动验证效果需要在实际浏览器环境中确认。

完整操作见 [扩展说明](extension/README.md)。当前扩展版本为 `1.0.2`。

## GitHub Actions

工作流支持手动运行，默认每天北京时间 08:05 和 12:18 运行，并发任务排队执行。工作流包含定时保活步骤，运行时间可能受 GitHub 排队影响。

在仓库 Settings → Secrets and variables → Actions 配置对应的 Secrets。

| 名称 | 用途 |
| --- | --- |
| `GLADOS_COOKIES` | 多账号 JSON 数组，启用多账号引擎 |
| `GLADOS_EXCHANGE_PLAN` | 可选 `plan100`、`plan200`、`plan500`，填写后启用积分兑换 |
| `GLADOS_VERBOSE` | 填写 `true` 开启详细日志 |
| `SERVERCHAN_SENDKEY` | Server 酱 SendKey |
| `PUSHDEER_SENDKEY` | PushDeer SendKey |
| `TWOCAPTCHA_API_KEY` | 可选的 2Captcha 付费求解服务 |

`GLADOS_COOKIES` 示例。

```json
[
  {
    "name": "主账号",
    "origin": "glados.cloud",
    "cookie": "gld:sess=填写会话; gld:sess.sig=填写签名",
    "user-agent": "填写创建会话的浏览器 User-Agent"
  },
  {
    "name": "其他账号",
    "origin": "railgun.info",
    "cookie": "填写该账号完整 Cookie"
  }
]
```

每个账号支持 `name`、`origin`、`cookie`、`user-agent` 四个字段。Cookie 重复时自动去重，未配置域名时依次探测 8 个内置站点。设备不匹配且未指定 UA 时，会根据登录设备平台重试一次。

多账号任务分别判断成功、重复签到和失败，查询总积分后统一推送。兑换只在成功或重复签到后执行，兑换请求关闭自动重试。任一账号签到失败，工作流返回失败。

## 现有配置兼容

原有单账号 `COOKIE`、`USER_AGENT`、`SERVE`、`SCKEY` 继续可用。

- 只使用原配置时，执行原有单账号流程。
- 配置 `GLADOS_COOKIES`、积分兑换、详细日志或新版推送字段时，进入多账号流程。
- 多账号流程可使用原 `COOKIE` 和 `USER_AGENT` 生成一个账号。
- 原 `SERVE=on` 时，`SCKEY` 可作为 `SERVERCHAN_SENDKEY` 的兼容配置。
- 配置了 `GLADOS_COOKIES` 时，账号数组提供各账号的 Cookie 和 User-Agent。

## Turnstile 与第三方求解

HTTP 流程在收到 `reason=turnstile` 后，可用 `TWOCAPTCHA_API_KEY` 请求一次 2Captcha 求解，再用新 challenge 提交验证令牌。单账号和多账号流程均支持此配置。

每次账号处理最多创建一个付费求解任务，最长等待 180 秒，并受 challenge 有效期限制。2Captcha 接收签到页面地址、公开 sitekey、`action=checkin` 和本次 nonce。配置该 Key 后，遇到验证要求会消耗服务账户余额。

第三方令牌被 GLaDOS 接受的情况需要真实验证。官方浏览器扩展流程也可能遇到人工验证要求。

## 本地运行

```powershell
python -m pip install -r requirements.txt
python checkin.py
```

可在脚本同目录创建已被 Git 忽略的 `config.json`。环境变量优先。

```json
{
  "COOKIE": "填写当前登录会话 Cookie",
  "USER_AGENT": "填写同一浏览器 User-Agent",
  "SERVE": "off",
  "SCKEY": ""
}
```

多账号本地配置可直接使用 JSON 数组。

```json
{
  "GLADOS_COOKIES": [
    {
      "name": "主账号",
      "origin": "glados.cloud",
      "cookie": "填写完整 Cookie",
      "user-agent": "填写浏览器 User-Agent"
    }
  ],
  "SERVERCHAN_SENDKEY": "",
  "PUSHDEER_SENDKEY": "",
  "GLADOS_EXCHANGE_PLAN": ""
}
```

Playwright 入口为 `python browser_checkin.py`，使用前执行 `python -m playwright install chromium`。Linux 有界面运行需要虚拟显示，例如 `xvfb-run -a python browser_checkin.py`。

## 验证

```powershell
python -m unittest -v
node extension/test-classify.js
```

测试使用模拟请求，覆盖单账号与多账号配置、结果判断、第三方求解、兑换重试设置、日志脱敏及扩展 Cookie 规则隔离。

## 源码来源与许可

多账号核心 `multi_checkin.py`、`logging_config.py` 和 `extension/` 基于 [Devilstore/Glados-Railgun-checkin](https://github.com/Devilstore/Glados-Railgun-checkin) 的提交 `8ca67db195ebb40cc91951005d0f2bfc63daaf72`，保留原作者 MIT 许可。兼容配置、失败退出状态和 Cookie 规则范围已针对本仓库调整。

许可见 [LICENSE](LICENSE)。
