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
    normalized_from = normalize_to_utc_naive(from_time)
    normalized_to = normalize_to_utc_naive(to_time)
    
    if normalized_from is None:
        normalized_from = default_from if default_from is not None else get_utc_now_naive()
    
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

#### 边界条件
1. **to_time < from_time**：返回 HTTP 400 错误（无效范围）
2. **to_time == from_time**：允许，表示查询精确等于该时间点的记录
   - 查询条件：`reminder_time >= from_time AND reminder_time <= to_time`
   - 当 `from_time == to_time` 时，等价于精确匹配
3. **to_time > from_time**：正常查询时间范围内的记录

### 数据库存储

- 所有时间存储为 **naive datetime**（无时区信息）
- 语义上统一表示 **UTC 时间**
- 查询时所有参数先标准化为 UTC naive datetime 再比较
"""
