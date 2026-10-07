# 验证与变更报告

## 结果

- 定向逻辑/共享层测试：48 passed。
- 共享快照离线重建：PASS，`slate_raw_5496ac532a49_asof_20261004_100640`，roster `899`。
- V4 离线运行：PASS，`{'total': 899, 'computed': 223, 'A': 9, 'B': 98, 'C': 68, 'N': 48, 'neutral': 41, 'missing_data': 0, 'insufficient_training': 0, 'not_prematch': 635, 'errors': 0}`。
- 旧逻辑变更前仍保存于备份目录；历史记录没有用新概率回刷。
- 变更前未开赛可比行：`899`；其中赛前字段变化数：`899`（正式发布前还需由 delivery verify 再校验 started-lock）。

## 解释

这不是用近期红黑调参，也不是把盘口方向反买。新路径只改变 `logic_change_at` 之后、尚未冻结的判断；已开赛/已结算行只允许补状态、比分、结算和 PnL。

## 尚未声称

当前仍是 `UNCALIBRATED_SHADOW` / `FAIR_LINE_UNCALIBRATED`，本报告没有把离线开发样本包装成独立时间外成功证据。未来冻结样本需要按日期滚动验证。
