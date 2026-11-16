# GLADOS自动签到脚本（新版）

![GLaDOS Checkin](https://img.shields.io/badge/GLaDOS-Checkin-brightgreen?style=flat-square&logo=github-actions)
![Python](https://img.shields.io/badge/Python-3.9+-blue?style=flat-square&logo=python)

本项目基于 GitHub Actions 实现 GLaDOS 网站的每日自动签到，并通过 Server 酱推送签到结果至微信。

## 📋 功能特点

*   **全自动运行**：利用 GitHub Actions 每日定时触发，无需人工干预。
*   **安全合规**：所有敏感信息（Cookie、Key）均存储在 GitHub Secrets 中，不会在代码中泄露。
*   **状态推送**：支持通过 Server 酱实时推送签到结果和账户剩余天数。
*   **双触发模式**：支持每日定时自动执行，也支持在 GitHub 后台手动点击触发。

## 🛠️ 配置步骤

### 1. 获取相关参数
*   **GLaDOS Cookie**：登录 [GLaDOS](https://glados.rocks/)，打开开发者工具 (F12)，在网络 (Network) 选项卡中找 `checkin` 请求，复制其 Header 中的 `cookie`。
*   **Server 酱 SCKEY**：前往 [Server 酱官网](https://sct.ftqq.com/) 获取推送密钥（SCKEY）。

### 2. 设置 GitHub Secrets
在你的 GitHub 仓库中，依次点击 `Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`，添加以下变量：

| 变量名 | 必填 | 描述 |
| :--- | :--- | :--- |
| `COOKIE` | 是 | 填写获取到的 GLaDOS Cookie |
| `USER_AGENT` | 建议配置 | 创建此登录会话的浏览器的完整 User-Agent，留空使用 Windows Chrome 默认标识 |
| `SERVE` | 是 | 是否开启通知，填 `on` 或 `off` |
| `SCKEY` | 否 | 填写 Server 酱的 SCKEY |
| `TWOCAPTCHA_API_KEY` | 需要自动求解时填写 | 2Captcha 账户的 API Key，求解会消耗该账户余额 |

在创建登录会话的浏览器中，打开开发者工具的 Network，刷新签到页面，选择 `status` 请求，将 Request Headers 中的 `user-agent` 完整单行值填入 `USER_AGENT`。只填写值。

GitHub 定时任务运行 `python checkin.py`。脚本先正常提交签到，服务端要求 Turnstile 时，使用新 challenge 调用 2Captcha，再提交求解令牌。每天已签到的响应会直接返回成功。

每次运行最多创建一个付费求解任务，最长等待 180 秒，并受当前 challenge 有效期限制。余额不足、任务超时或服务端拒绝令牌会返回失败并推送原因。求解兼容性需要通过真实首次签到验证。

2Captcha 会收到签到页面地址、公开 sitekey、`action=checkin` 和本次 nonce。该实现向 GLaDOS 发送 Cookie，向 2Captcha 发送其 API Key。配置该 Key 后，遇到验证要求会自动使用付费求解服务。接口说明见 [2Captcha 官方文档](https://2captcha.com/api-docs/cloudflare-turnstile)。

若返回 `device-mismatch`，请核对 `USER_AGENT` 与登录浏览器是否一致。若返回 `code=-2` 或“没有权限”，请确认当前浏览器的 `status` 请求正常，再更新 `COOKIE`。脚本会让实际签到失败的 Actions 任务返回失败。

### 本地运行

安装依赖后运行 `python checkin.py`。也可在脚本同目录创建 `config.json`，环境变量优先于本地配置。浏览器入口为 `python browser_checkin.py`，运行前需要执行 `python -m playwright install chromium`。

```json
{
  "COOKIE": "填写当前登录会话的 Cookie",
  "USER_AGENT": "填写同一浏览器的完整 User-Agent",
  "SERVE": "off",
  "SCKEY": "",
  "TWOCAPTCHA_API_KEY": "填写 2Captcha API Key"
}
```

`config.json` 已被 Git 忽略。测试命令为 `python -m unittest -v`，测试使用模拟请求。

### 3. 启用并测试脚本
1.  点击仓库顶部的 **Actions** 标签页。
2.  在左侧选择 **GLaDOS Daily Checkin** 工作流。
3.  点击右侧的 **Run workflow** 下拉菜单，点击 **Run workflow** 按钮进行手动测试。
4.  若出现绿色对号，说明配置成功。

## ⏰ 定时任务说明
脚本默认配置在 **北京时间每日上午 08:05** 左右运行（对应 Cron 表达式 `5 0 * * *`）。
> GitHub Actions 可能排队，实际运行时间可能延后。

## 📜 免责声明
本项目仅供编程学习交流使用，请勿用于商业用途。开发者不对因使用本脚本导致的任何账号问题负责。
