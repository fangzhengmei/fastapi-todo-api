from datetime import datetime, timezone, timedelta
from typing import Optional


def normalize_to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    
    return dt


def get_utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_time_for_error(dt: datetime) -> str:
    return f"{dt.isoformat()}Z"


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
            from_str = format_time_for_error(normalized_from)
            to_str = format_time_for_error(normalized_to)
            raise ValueError(
                f"Invalid time range: to_time ({to_str}) cannot be earlier than from_time ({from_str}). "
                f"Note: Both parameters are explicitly provided, so range validation is enforced. "
                f"If you intended to query past data, use only 'to_time' parameter."
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

#### 缺省参数语义规则（完整覆盖）

| 场景 | from_time | to_time | 详细行为 | 查询条件 |
|------|-----------|---------|----------|----------|
| **场景1** | 缺省 | 缺省 | 使用当前 UTC 时间作为 from_time，无上限 | `reminder_time >= now` |
| **场景2** | 提供 | 缺省 | 使用提供的 from_time，无上限 | `reminder_time >= from_time` |
| **场景3a** | 缺省 | 提供（> 当前时间） | 使用当前 UTC 时间作为 from_time，to_time 有效 | `now <= reminder_time <= to_time` |
| **场景3b** | 缺省 | 提供（== 当前时间） | 使用当前 UTC 时间作为 from_time，精确匹配 | `reminder_time == now` |
| **场景3c** | 缺省 | 提供（< 当前时间） | 使用当前 UTC 时间作为 from_time，返回空列表（**不报错**） | 无匹配 |
| **场景4** | 提供 | 提供 | 校验 `to_time >= from_time`，失败则报错 | 取决于校验结果 |

#### 边界条件详细规则

**核心原则：仅当两个参数都显式提供时，才进行范围校验！**

| 条件 | 行为 | 示例 |
|------|------|------|
| **to_time < from_time（双参数都提供）** | 返回 **HTTP 400** 错误（无效范围） | `from=12:00, to=10:00` → 400 错误 |
| **to_time < from_time（单参数提供）** | **不返回错误**，返回空列表 | 仅 `to=10:00`（当前时间 12:00）→ 空列表 |
| **to_time == from_time** | 允许，精确匹配该时间点 | `from=10:00, to=10:00` → 精确匹配 |
| **to_time > from_time** | 正常查询时间范围内的记录 | `from=10:00, to=12:00` → 范围查询 |

#### 错误返回格式

**HTTP 400 错误响应**（仅当双参数都提供且范围无效时）：

```json
{
  "detail": "Invalid time range: to_time (2026-05-01T10:00:00Z) cannot be earlier than from_time (2026-05-01T12:00:00Z). Note: Both parameters are explicitly provided, so range validation is enforced. If you intended to query past data, use only 'to_time' parameter."
}
```

**错误消息包含**：
1. 具体的时间值（带 Z 后缀表示 UTC）
2. 说明为什么触发校验（双参数都提供）
3. 提示如何查询过去数据（仅使用 to_time）

### 极端时间值处理

| 场景 | 行为 |
|------|------|
| **极远未来时间**（如 9999-12-31） | 正常处理，不报错 |
| **极远过去时间**（如 0001-01-01） | 正常处理，不报错 |
| **微秒级精度** | 保留完整微秒精度进行比较 |

### 数据库存储

- 所有时间存储为 **naive datetime**（无时区信息）
- 语义上统一表示 **UTC 时间**
- 查询时所有参数先标准化为 UTC naive datetime 再比较
"""
