# 设计与面试说明

## 为什么采用 ODS → DWD → DWS → ADS

- **ODS** 保留原始订单版本和行为上报，便于追踪更新与重复记录。
- **DWD** 用 `ROW_NUMBER()` 保留每个 `order_id` / `event_id` 的最新版本，然后过滤非法记录。对订单先排名再校验，避免错误的最新版本被过滤后，旧订单状态被误认为当前状态。
- **DWS** 按业务日期 `dt` 产出 DAU、付费用户、支付订单数、GMV 和付费转化率。付费用户是当日活跃用户与当日支付用户的交集；订单数和 GMV 则来自当日全部有效支付订单。
- **ADS** 输出每日展示字段，并用窗口函数计算三日滚动 GMV 与 GMV 日环比。

## 分区与重跑

`DWD` 和 `DWS` 表按业务日期 `dt` 分区。`INSERT OVERWRITE TABLE ... PARTITION (dt)` 是动态分区写入，`SELECT` 的最后一列提供 `dt`。同样的 7 天数据再次运行时，出现的日期分区被重新计算，而非追加重复记录。全动态分区在默认 strict 配置下需要 `hive.exec.dynamic.partition.mode=nonstrict`。[官方说明](https://hive.apache.org/docs/latest/language/languagemanual-dml/)

示例脚本会从全部原始文件重建这 7 天数据。真实生产系统需要明确**变更影响的业务日期**，并为晚到状态更新设置回刷窗口或变更追踪；只读取当天新入湖数据，会漏掉次日取消导致的历史日期 GMV 调整。若改用不同日期范围的数据，本演示不会自动删除已存在但不再出现在源数据中的旧分区。

本演示以“有有效行为的日期”为 DWS 的日期集合；完全没有行为的日期不会生成一行零值。要给报表展示连续日历，需再加入日期维表并补齐空日期。

## 表与文件格式

ODS 使用便于加载示例 CSV 的 TEXTFILE；DWD、DWS 和 ADS 指定 ORC。目标表明确设为非事务表，以便使用 `INSERT OVERWRITE`。在启用 ACID 的事务表上，Hive 对 `INSERT OVERWRITE` 有限制。[Hive DDL](https://hive.apache.org/docs/latest/language/languagemanual-ddl/) · [Hive DML](https://hive.apache.org/docs/latest/language/languagemanual-dml/)

## 当前验证边界

`scripts/validate_local.py` 使用 SQLite 执行仓库中 03–05 脚本的 `SELECT`，与生成器提供的独立预期结果对比，并运行五条异常检查。Hive 端另有 `sql/07_assert_quality.sql`，用 `assert_true` 让异常结果终止脚本。当前本地校验不验证 Hive 的解析、数据加载、ORC 编码、动态分区配置、容器权限、作业调度或性能。因此完成一次真实 Hive 运行后，应记录 Beeline 输出、`SHOW PARTITIONS`、异常检查和最终指标，再更新 README 的验证状态。

