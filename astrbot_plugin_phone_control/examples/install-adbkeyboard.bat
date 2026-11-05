@echo off
chcp 65001 >nul
echo ===== 安装 ADBKeyboard（中文输入用）=====
set ADB=adb
set APK=%~dp0..\ADBKeyboard.apk
if not exist "%ADB%" (
  echo [X] 找不到 adb
  pause & exit /b 1
)
if not exist "%APK%" (
  echo [!] 包内没找到 ADBKeyboard.apk
  echo     去 https://github.com/senzhk/ADBKeyBoard 下载后放到插件根目录，再跑一次
  pause & exit /b 1
)
"%ADB%" install -r "%APK%"
"%ADB%" shell ime enable com.android.adbkeyboard/.AdbIME
"%ADB%" shell ime list -s
echo.
echo [OK] 装完并已启用；插件会自动切到它打中文，打完切回你原来的输入法
pause
