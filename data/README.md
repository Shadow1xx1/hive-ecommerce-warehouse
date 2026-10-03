# 数据说明

`orders_raw.csv` 与 `events_raw.csv` **没有表头**，与 `sql/01_create_tables.sql` 的 ODS 列顺序一致。

| 文件 | 列顺序 |
|---|---|
| `orders_raw.csv` | `order_id,user_id,order_time,amount,status,updated_at,ingest_seq` |
| `events_raw.csv` | `event_id,user_id,event_time,event_type,ingest_seq` |

`ingest_seq` 是模拟入湖顺序，用于同一业务键更新时间相同时稳定破平局。`expected_daily_metrics.csv` 与 `expected_dashboard.csv` **有表头**，是 Python 参考实现计算的预期结果，不是声称从 Hive 导出的结果。`manifest.json` 记录固定种子和行数。

重建数据：

```bash
python scripts/generate_data.py
```

全部数据都是模拟数据。请勿把示例金额或规模写成真实业务成果。

