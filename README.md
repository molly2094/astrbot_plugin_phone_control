# astrbot-plugin-phone-control

> 让 AstrBot 里的 bot 用 adb 操作一台安卓手机：解锁、刷抖音 / B站、发评论、发私信、读界面、截图。
> **能验证才说成功** —— 读不到就说读不到，发不出去就说发不出去。

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()
[![AstrBot](https://img.shields.io/badge/AstrBot-4.29%2B-orange)]()

---

## 它到底能干什么

```
你：手机锁着，你解开，刷两条抖音，看到想说的就评一句
她： ✅ 用 PIN 解锁 → 打开抖音 → 刷两条 → 评一句 → 回桌面 → 告诉你刷到了什么
```

13 个工具：状态 / 截图 / 读界面 / 多步流程 / 解锁 / 搜索 / 抖音（刷·评·私信·退） / B站（刷·评）。

---

## 快速开始（5 分钟）

1. 装 **Android platform-tools**，把 `adb` 加进 PATH（或填到插件配置的 `adb_path`）；
2. 手机开 **USB 调试**，连电脑，允许调试；
3. 把 `astrbot_plugin_phone_control/` 放进 AstrBot 的 `data/plugins/`，重启；
4. 后台插件页填 **`owner_uids`（谁能用）**；
5. 想让它自己解锁：把 PIN 写进 `data/plugin_data/astrbot_plugin_phone_control/lock.json`。

详细步骤见下方"安装"，或用 `astrbot_plugin_phone_control/examples/check-env.bat` 自检。

---

# 手机控制（astrbot_plugin_phone_control）

让 AstrBot 里的 bot 用 **adb** 操作一台安卓手机：解锁、看界面、点按钮、打中文、
刷抖音 / B站、发评论、发私信、搜商品、截图回传。

> 设计原则：**能验证才说成功**。读不到界面就说读不到，发不出去就说发不出去，不用“缓存/锁屏”搪塞。

---

## 一、能做什么

| 工具 | 作用 | 写操作 |
|---|---|---|
| `phone_status` | 连接状态、型号、安卓版本、分辨率、电量、前台应用、**是否锁屏** | 只读 |
| `phone_screenshot` | 截图并发到聊天里 | 只读 |
| `phone_ui_dump` | 读当前界面的控件（文字 / id / 坐标） | 只读 |
| `phone_unlock` | 用本地配置的 PIN 解锁（锁屏时先调它） | 写 |
| `phone_run` | 一次跑完整段步骤（open/tap/text/key/swipe/wait/sleep/notify） | 写 |
| `phone_search` | 拼多多 / 淘宝 / 京东 文字搜索，只搜不买 | 写 |
| `phone_search_image` | 识图搜同款（把图推给拼多多） | 写 |
| `phone_douyin_browse` | 刷抖音：逐条读出作者 / 文案 / 点赞，刷完可自动回桌面 | 写 |
| `phone_douyin_comment` | 在当前视频下发一条评论（自动退出评论面板） | **写** |
| `phone_douyin_dm` | 给指定昵称的人发私信 | **写** |
| `phone_douyin_exit` | 退出抖音（回桌面 / 结束进程） | 写 |
| `phone_bili_browse` | 刷 B站 推荐流，读标题 / UP 主 | 写 |
| `phone_bili_comment` | 在当前 B站 视频下发评论 | **写** |

---

## 二、安装

### 1. 装 adb（platform-tools）

下载 Google 官方压缩包并解压到一个固定目录，例如：

```
C:\path\to\platform-tools\adb.exe
```

验证：

```
C:\path\to\platform-tools\adb.exe version
```

### 2. 手机准备

1. 设置 → 关于手机 → 连点「版本号」7 次，开启开发者选项；
2. 设置 → 系统和更新 → 开发人员选项 → 打开 **USB 调试**；
3. 数据线连电脑，通知栏选 **「传输文件」**；
4. 手机上弹「允许 USB 调试吗」→ 勾选 **一律允许** → 确定。

验证：

```
adb devices
# 4HDVB23316013771   device
```

> 如果显示 `unauthorized`，是没点允许；如果什么都不显示，是 USB 调试没开。

### 3. 装 ADBKeyboard（中文输入必需）

1. 下载 `ADBKeyboard.apk`（开源项目 `senzhk/ADBKeyBoard`）；
2. `adb install -r ADBKeyboard.apk`；
3. `adb shell ime enable com.android.adbkeyboard/.AdbIME`。

不装也能用，但 `text` 只能打英文数字；插件会自动切到它、打完再切回你的输入法
（原输入法存在 `plugin_data/astrbot_plugin_phone_control/ime.json`）。

### 4. 装插件

把本目录放到：

```
<AstrBot 实例>/data/plugins/astrbot_plugin_phone_control/
```

重启 AstrBot，日志里应出现：

```
Plugin astrbot_plugin_phone_control (1.0.0)
```

### 5. 配 PIN（可选，但强烈建议）

新建文件：

```
<AstrBot 实例>/data/plugin_data/astrbot_plugin_phone_control/lock.json
```

内容：

```json
{
  "pin": "你的锁屏数字密码"
}
```

- **不打日志、不进提示词**，只有解锁那一刻读一次；
- 文件是明文的，注意电脑本身的安全；
- 手机重启后第一次仍需手动解锁（Android 加密机制）。

---

## 三、配置

```json
{
  "adb_path": "C:\\path\\to\\platform-tools\\adb.exe",
  "owner_uids": ["你的QQ号"],
  "allow_private_only": true,
  "step_timeout_ms": 15000
}
```

| 项 | 说明 |
|---|---|
| `adb_path` | adb 路径 |
| `owner_uids` | 谁能用（按 QQ 号），**别的号调不动** |
| `allow_private_only` | 只在私聊响应，群里不响应 |
| `step_timeout_ms` | 单步超时 |

---

## 四、`phone_run` 的步骤语法

```json
[
  {"op": "open", "query": "计算器"},
  {"op": "tap", "text": "发送"},
  {"op": "text", "value": "中文也行"},
  {"op": "key", "key": "back"},
  {"op": "swipe", "direction": "up"},
  {"op": "wait", "text": "成功", "timeoutMs": 8000},
  {"op": "notify_open"},
  {"op": "sleep", "ms": 800}
]
```

- 任一步失败就停，并列出当前界面上有哪些文字；
- `tap` 支持 `text` / `id` / 直接 `x`+`y`；
- `open` 支持 `query`（搜索打开）或 `package`（直接拉起）。

---

## 五、为什么这样设计（踩过的坑）

这一版不是一次写完的，下面每条都是真实踩出来的：

| 坑 | 现象 | 解决 |
|---|---|---|
| **锁屏判断误报** | `dumpsys window` 里永远有 `Keyguard` 字样，一 grep 就永远“锁屏” | 只看 `mDreamingLockscreen` 和前台窗口包名 |
| **界面读到旧的** | dump 失败时 `/sdcard/ui.xml` 还是上次的内容，读出来是旧界面 | 每次先 `rm` 再 dump，没输出 `dumped to` 就算失败 |
| **安全键盘点不了** | 锁屏密码页 `uiautomator` 看不到控件、输入法广播也进不去 | 密码走底层 `input text`，并单独做 `phone_unlock` |
| **评论面板挡住** | 评完没退出面板，上滑是在滚评论，刷不到下一条 | 评完主动关面板，每次滑动前再检查一次 |
| **启动页误判** | 抖音 `mResumedActivity` 一直报 `SplashActivity`，其实已在刷视频 | 用截图 + 视觉判断“是否在推荐流” |
| **打错输入框** | 停在搜索页时评论，文字打进了搜索框 | 评论前强制确认在视频页，不在就取消 |

---

## 六、行为边界（写在代码里）

- **只对 `owner_uids` 私聊生效**，群里和不认识的号调不动；
- 不做 **安装/卸载/支付/转账/删文件**（没有对应工具）；
- 评论有 **每日上限**（默认 8 条，记在 `comments.json`），超过会拒绝；
- 发评论、发私信前会检查是否在视频页，不在就取消而不是瞎点。

---

## 七、常见问题

**Q：她说“没有连接手机”**
`adb devices` 里没有设备。检查数据线、USB 调试、手机上是否点了允许。

**Q：她说“PIN 解锁失败”**
1. `lock.json` 里 PIN 对不对；
2. 锁屏上有没有别的弹窗（来电、更新）；
3. 手动试一次同样的步骤，看能不能解开。

**Q：中文打不出来**
没装 ADBKeyboard，或者它被禁用。`adb shell ime list -s` 能看到它才行。

**Q：刷抖音刷来刷去都是同一条**
评论面板没关掉。看日志有没有“已退出评论面板”；没有的话把当时的截图发出来。

**Q：评论发出去了但我看不到**
截图就是证据；抖音评论有时要审核几秒。

---

## 八、日志

```
<AstrBot 实例>/data/logs/astrbot.log
```

搜关键词：

| 关键词 | 看什么 |
|---|---|
| `使用工具：phone_` | 她调了哪些工具、参数是什么 |
| `Tool \`phone_` | 工具返回了什么 |
| `[phone] 已用 PIN 解锁` | 解锁成功 |
| `[douyin] 粗读` | 视频理解走的是哪条路 |

---

## 九、搭配建议

- **自由活动**：配合 `astrbot_plugin_free_time`（定时给她一个自己的回合），她会自己去刷抖音、想评就评；
- **视频理解**：刷到的视频可以接视觉模型（`glm-4.6v` / `Qwen3-Omni`）做内容理解，再写进记忆；
- **记忆**：本插件只负责操作手机，刷到的内容写记忆需要另一条链路（可用 memory 服务）。

---

## 十、许可与风险

- 这是**你自己的手机**，工具会真实点击、真实发评论/私信；
- 抖音、B站 等平台对自动操作有风控，频率过高可能被限制，**每日限额别关**；
- PIN 明文存储，电脑被人用等于手机被解开，自行评估。

---

## 免责声明

- 本插件会**真实操作你的手机**：点击、输入、发评论、发私信。请只在自己的设备与账号上使用。
- 抖音 / B站 等平台对自动化有风控，**请保留每日限额**，频率过高可能导致账号受限。
- `lock.json` 里存的是锁屏密码明文，请自行评估电脑安全。
- 本项目仅供个人学习与自用，因使用产生的账号风险由使用者自行承担。
