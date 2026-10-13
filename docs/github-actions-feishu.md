# GitHub Actions 每日足球更新与飞书推送

工作流文件是 `.github/workflows/football-daily-feishu.yml`，每天北京时间 07:00（UTC 23:00）触发，也可以在 GitHub Actions 页面手动运行。工作流声明 `contents: write`，让本机发布器可以用 Actions token 推送 gh-pages；并用并发锁避免同一时段重复发布。

完整 V3/V4 更新依赖本机现有的 `D:\codex` 目录、Excel 底稿和本地缓存，因此工作流使用 Windows self-hosted runner。Runner 需要能访问：

- `D:\codex\技能项目\football_update\run_football_update.py`
- `D:\codex\outputs\football_odds_trader`
- `D:\python\python.exe`（如果不存在，工作流会回退到 PATH 中的 Python）

在仓库 Settings → Secrets and variables → Actions → New repository secret 中新增：

```text
Name: FEISHU_WEBHOOK_URL
Value: <飞书机器人 Webhook 地址>
```

Webhook 只通过 Secret 注入，不写入代码、Excel、日志或提交记录。工作流完成后会发送日期、赛事总数、V3/V4 可投数量、缩表审计状态和历史统计条数，并附带 `https://simondongxiao.github.io/odds/v4/?date=YYYY-MM-DD` 看板链接；V4 可投数量按所选列表日 JSON 的 `side=giving` + `side=receiving` 计算，C/NO_BET 不计入可投；更新失败时也会发送失败提醒。运行前会检查 D:\codex 路径和 Secret，缺少生产目录时直接失败并给出原因。

如使用 GitHub CLI，可在已登录的机器上执行：

```powershell
gh secret set FEISHU_WEBHOOK_URL --repo simondongxiao/odds
```

命令会交互式读取地址，不要把地址写入命令历史或仓库文件。
