# 更新日志

## v1.0.0（2026-11-05）

首个打包版本。13 个工具，全部在真机（华为 nova 10 / HarmonyOS 4.2 / Android 12）上跑过。

### 新增
- `phone_status` / `phone_screenshot` / `phone_ui_dump` / `phone_run`
- `phone_unlock`（PIN 自动解锁）
- `phone_search` / `phone_search_image`
- `phone_douyin_browse` / `phone_douyin_comment` / `phone_douyin_dm` / `phone_douyin_exit`
- `phone_bili_browse` / `phone_bili_comment`

### 修复（开发过程中踩的坑）
- 锁屏判断不再 grep `Keyguard`（会永远误报），改看 `mDreamingLockscreen`
- 读界面先删 `/sdcard/ui.xml`，避免读到上一次的旧界面
- 锁屏密码页改用 `input text`，绕开安全键盘
- 评论后主动关闭评论面板，否则上滑只滚评论
- 抖音改用“截图+视觉”判断是否进推荐流（`SuspendedActivity` 不可靠）
- 评论前强制确认在视频页，避免把文字打进搜索框
