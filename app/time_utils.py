from datetime import datetime, timezone
from typing import Optional


def normalize_to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    
    return dt


def get_utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def validate_time_range(
    from_time: Optional[datetime],
    to_time: Optional[datetime],
    default_from: Optional[datetime] = None
) -> tuple[datetime, Optional[datetime]]:
    from_time_explicit = from_time is not None
    to_time_explicit = to_time is not None
    
    normalized_from = normalize_to_utc_naive(from_time)
    normalized_to = normalize_to_utc_naive(to_time)
    
    if normalized_from is None:
        normalized_from = default_from if default_from is not None else get_utc_now_naive()
    
    if from_time_explicit and to_time_explicit:
        if normalized_to is not None and normalized_to < normalized_from:
            from_str = f"{normalized_from.isoformat()}Z"
            to_str = f"{normalized_to.isoformat()}Z"
            raise ValueError(
                f"Invalid time range: to_time ({to_str}) cannot be earlier than from_time ({from_str})"
            )
    
    return normalized_from, normalized_to


TIME_POLICY_DOC = """
## 时间处理策略

### 输入时间格式

系统支持两种时间输入格式：

1. **带时区时间**（推荐）
   - 格式：ISO 8601 格式，如 `2026-05-01T10:00:00+08:00`
   - 处理：自动转换为 UTC 时间后存储
   - 示例：北京时间 `2026-05-01T18:00:00+08:00` → 存储为 UTC `2026-05-01T10:00:00`

2. **不带时区时间**
   - 格式：如 `2026-05-01T10:00:00`
   - 处理：**明确视为 UTC 时间**，保持不变
   - 示例：`2026-05-01T10:00:00` → 存储为 UTC `2026-05-01T10:00:00`

### 时间范围查询策略

#### 参数说明
- `from_time`：查询起始时间（包含），默认值为当前 UTC 时间
- `to_time`：查询结束时间（包含），可选，不提供则无上限

#### 缺省参数语义规则

| 场景 | from_time | to_time | 行为 |
|------|-----------|---------|------|
| 场景1 | 缺省 | 缺省 | 使用当前 UTC 时间作为 from_time，无上限 |
| 场景2 | 提供 | 缺省 | 使用提供的 from_time，无上限 |
| 场景3 | 缺省 | 提供 | 使用当前 UTC 时间作为 from_time，使用提供的 to_time |
| 场景4 | 提供 | 提供 | 使用提供的 from_time 和 to_time |

#### 边界条件

**仅当两个参数都显式提供时，才进行范围校验：**

1. **to_time < from_time（双参数都提供）**：返回 HTTP 400 错误（无效范围）
   - 错误消息示例：`Invalid time range: to_time (2026-05-01T10:00:00Z) cannot be earlier than from_time (2026-05-01T12:00:00Z)`

2. **to_time < from_time（单参数提供）**：**不返回错误**，返回空列表
   - 示例：只提供 to_time 且 to_time 在过去 → 返回空列表，不报错
   - 示例：提供 from_time 且 from_time 在未来，不提供 to_time → 正常查询

3. **to_time == from_time**：允许，表示查询精确等于该时间点的记录
   - 查询条件：`reminder_time >= from_time AND reminder_time <= to_time`
   - 当 `from_time == to_time` 时，等价于精确匹配

4. **to_time > from_time**：正常查询时间范围内的记录

### 数据库存储

- 所有时间存储为 **naive datetime**（无时区信息）
- 语义上统一表示 **UTC 时间**
- 查询时所有参数先标准化为 UTC naive datetime 再比较
"""
