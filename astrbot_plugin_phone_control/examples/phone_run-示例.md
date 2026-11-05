# phone_run 常见流程示例

## 1. 打开计算器算一道题

```json
[
  {"op": "open", "query": "计算器"},
  {"op": "tap", "text": "1"},
  {"op": "tap", "text": "2"},
  {"op": "tap", "text": "+"},
  {"op": "tap", "text": "3"},
  {"op": "tap", "text": "4"},
  {"op": "tap", "text": "="},
  {"op": "sleep", "ms": 800}
]
```

## 2. 打开设置 → 关蓝牙

```json
[
  {"op": "open", "query": "设置"},
  {"op": "tap", "text": "蓝牙"},
  {"op": "sleep", "ms": 1200}
]
```

## 3. 浏览器里搜一句话

```json
[
  {"op": "open", "query": "Chrome"},
  {"op": "sleep", "ms": 2000},
  {"op": "tap", "text": "搜索"},
  {"op": "text", "value": "今天天气"},
  {"op": "key", "key": "enter"},
  {"op": "wait", "text": "℃", "timeoutMs": 10000}
]
```

## 4. 微信给某个人发消息（演示，谨慎使用）

```json
[
  {"op": "open", "query": "微信"},
  {"op": "tap", "text": "搜索"},
  {"op": "text", "value": "张三"},
  {"op": "tap", "text": "张三"},
  {"op": "tap", "text": "发消息"},
  {"op": "text", "value": "在忙，晚点回"},
  {"op": "tap", "text": "发送"}
]
```

> 注：`tap` 的 `text` 是模糊匹配（包含即命中）；找不到会停住并列出当前界面的文字。
