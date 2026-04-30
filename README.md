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
在你的 GitHub 仓库中，依次点击 `Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`，添加以下三个变量：

| 变量名 | 必填 | 描述 |
| :--- | :--- | :--- |
| `COOKIE` | 是 | 填写获取到的 GLaDOS Cookie |
| `SERVE` | 是 | 是否开启通知，填 `on` 或 `off` |
| `SCKEY` | 否 | 填写 Server 酱的 SCKEY |

### 3. 启用并测试脚本
1.  点击仓库顶部的 **Actions** 标签页。
2.  在左侧选择 **GLaDOS Daily Checkin** 工作流。
3.  点击右侧的 **Run workflow** 下拉菜单，点击 **Run workflow** 按钮进行手动测试。
4.  若出现绿色对号，说明配置成功。

## ⏰ 定时任务说明
脚本默认配置在 **北京时间每日上午 08:05** 左右运行（对应 Cron 表达式 `5 0 * * *`）。
> **注意**：由于 GitHub Actions 调度器的排队机制，实际运行时间可能会比预定时间延迟 10-30 分钟。

## 📜 免责声明
本项目仅供编程学习交流使用，请勿用于商业用途。开发者不对因使用本脚本导致的任何账号问题负责。