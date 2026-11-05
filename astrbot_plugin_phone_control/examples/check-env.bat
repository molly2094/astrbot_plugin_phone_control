@echo off
chcp 65001 >nul
echo ===== 手机控制插件 环境自检 =====
echo.
set ADB=adb
if not exist "%ADB%" (
  echo [X] 找不到 adb：%ADB%
  echo     请先装 Android platform-tools，或在插件配置里改 adb_path
  goto :end
)
echo [OK] adb 存在
echo.
echo --- 设备列表 ---
"%ADB%" devices
echo.
echo --- 锁屏状态（mDreamingLockscreen）---
"%ADB%" shell dumpsys window | findstr /C:"mDreamingLockscreen"
echo.
echo --- ADBKeyboard 是否安装 ---
"%ADB%" shell pm list packages | findstr /C:"adbkeyboard"
echo.
echo --- 当前输入法 ---
"%ADB%" shell settings get secure default_input_method
:end
echo.
pause
