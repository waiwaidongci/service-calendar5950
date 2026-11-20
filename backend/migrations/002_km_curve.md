# 002 结单概率曲线（Kaplan-Meier）

## 结构变更

- `sla_runs` 新增列：`cutoff`（截点，ISO字符串可空）、`km_epoch`（截点代际，默认0）、
  `km_status`（idle/queued/running/completed/failed，默认idle）、`km_total`、`km_done`（批次进度，默认0）、`km_error`。
- 新表 `km_batches`：`run_id + epoch + batch_no` 唯一约束，存分批部分聚合（小组×业务分钟的结单/删失计数）。

`src.config.database.migrate()` 在 backend 与 worker 启动时幂等执行 `ALTER TABLE ... ADD COLUMN`（已存在则跳过）；
全新数据库由 `create_all` 直接建全。升级前请先备份。

## 口径

- 开单时间不晚于截点（含恰在截点）的底稿全部入样；截点前已结单按开单→结单业务分钟计事件；
  未结单（`closed` 为空）与截点后才结单的只随访到截点，按截点计删失。
- 每个业务分钟以当时仍在观察的全部样本为分母；同一分钟先记结单，再把该分钟结单与删失样本一并移出。
- 部分聚合按 (小组, 业务分钟) 计数相加合并，可交换可结合：批次乱序到达与整批核算结果一致。
- 底稿 `closed` 字段允许为空表示未结单；SLA 汇总仍只统计已结单，未结单数在 summary 单列。
