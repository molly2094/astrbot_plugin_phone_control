"""手机控制（QQ 版）：把 dsh-phone-control 那套 adb 工具搬给 AstrBot。

只读为主 + 有限操作；不做 install/卸载/支付类操作。
模型拿到的工具：phone_status / phone_screenshot / phone_ui_dump / phone_run。
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

PLUGIN_NAME = "astrbot_plugin_phone_control"

DEFAULT_ADB = "adb"
OWNER_IDS: set[str] = set()
ADBKEYBOARD = "com.android.adbkeyboard/.AdbIME"

DEFAULT_CONFIG = {
    "adb_path": DEFAULT_ADB,
    # 视觉读图（可选）：填了才会用截图去读抖音文案
    "vision_api_base": "",
    "vision_api_key": "",
    "vision_model": "glm-4v-flash",
    # 记忆服务（可选）：填了会把刷到的内容写进去
    "memory_url": "",
    "memory_ns": "",
    "owner_uids": list(OWNER_IDS),
    "allow_private_only": True,
    "step_timeout_ms": 15000,
}


@register(PLUGIN_NAME, "dsh", "手机控制（adb）：看界面、点按钮、打中文、跑多步流程", "1.0.0")
class PhoneControl(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.cfg = {**DEFAULT_CONFIG, **(config or {})}
        self.base = Path(StarTools.get_data_dir(PLUGIN_NAME))
        self.base.mkdir(parents=True, exist_ok=True)
        self.adb = str(self.cfg.get("adb_path") or DEFAULT_ADB)

    # ── 基础 ────────────────────────────────────────────
    def _run(self, args: list[str], timeout: float = 30) -> tuple[int, str, str]:
        try:
            p = subprocess.run([self.adb, *args], capture_output=True, timeout=timeout)
            return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
        except FileNotFoundError:
            return -1, "", f"找不到 adb：{self.adb}"
        except subprocess.TimeoutExpired:
            return -2, "", "adb 超时"

    def _devices(self) -> list[str]:
        _, out, _ = self._run(["devices"])
        return [line.split("\t")[0] for line in out.splitlines()[1:] if "\tdevice" in line]

    def _allowed(self, event: AstrMessageEvent) -> bool:
        uid = str(event.get_sender_id() or "")
        if self.cfg.get("allow_private_only", True) and not event.is_private_chat():
            return False
        return uid in {str(x) for x in self.cfg.get("owner_uids") or []}

    # ── UI 树 ───────────────────────────────────────────
    def _dump(self) -> str:
        """读控件树。必须先删旧文件：dump 失败时 /sdcard/ui.xml 会留着上次的内容，
        直接 cat 就会把「旧界面」当成当前界面读（她之前一直说"读到的是缓存的旧画面"就是这个）。"""
        for _ in range(2):
            self._run(["shell", "rm", "-f", "/sdcard/ui.xml"], timeout=15)
            code, out, err = self._run(["shell", "uiautomator", "dump", "/sdcard/ui.xml"], timeout=25)
            if "dumped to" not in f"{out}{err}" and "hierchary" not in f"{out}{err}":
                time.sleep(1.2)
                continue
            code, xml, _ = self._run(["shell", "cat", "/sdcard/ui.xml"], timeout=20)
            if code == 0 and len(xml) > 200:
                return xml
            time.sleep(1.2)
        return ""

    @staticmethod
    def _nodes(xml: str) -> list[dict]:
        nodes = []
        for m in re.finditer(r"<node[^>]*>", xml):
            tag = m.group(0)

            def attr(name):
                mm = re.search(rf'{name}="([^"]*)"', tag)
                return mm.group(1) if mm else ""

            bounds = attr("bounds")
            mm = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
            if not mm:
                continue
            x1, y1, x2, y2 = map(int, mm.groups())
            nodes.append({
                "text": attr("text"),
                "desc": attr("content-desc"),
                "id": attr("resource-id"),
                "cls": attr("class"),
                "clickable": attr("clickable") == "true",
                "center": ((x1 + x2) // 2, (y1 + y2) // 2),
            })
        return nodes

    def _tap_by(self, xml: str, *, text: str = "", rid: str = "") -> tuple[bool, str]:
        for node in self._nodes(xml):
            if text and (node["text"] == text or node["desc"] == text or text in node["text"]):
                x, y = node["center"]
                self._run(["shell", "input", "tap", str(x), str(y)])
                return True, f"点了「{text}」({x},{y})"
            if rid and node["id"].endswith(rid):
                x, y = node["center"]
                self._run(["shell", "input", "tap", str(x), str(y)])
                return True, f"点了 {rid} ({x},{y})"
        return False, f"界面上找不到 {text or rid}"

    def _preferred_ime(self) -> str:
        """用户的真实输入法：存在状态文件里；没有就取当前（排除 adbkeyboard）。"""
        state = self.base / "ime.json"
        try:
            if state.is_file():
                saved = json.loads(state.read_text(encoding="utf-8")).get("preferred", "")
                if saved and "adbkeyboard" not in saved.lower():
                    return saved
        except Exception:
            pass
        _, cur, _ = self._run(["shell", "settings", "get", "secure", "default_input_method"])
        cur = (cur or "").strip()
        if cur and "adbkeyboard" not in cur.lower():
            self._save_ime(cur)
            return cur
        return ""

    def _save_ime(self, ime: str) -> None:
        try:
            (self.base / "ime.json").write_text(json.dumps({"preferred": ime}), encoding="utf-8")
        except Exception:
            pass

    def _type_text(self, value: str, skill_switch: bool = True) -> str:
        """输入文本。含中文时自动切到 ADBKeyboard，打完切回原来的输入法。"""
        # 锁屏密码页是安全键盘：ADBKeyboard 的广播进不去，只能用 input text
        if self._is_locked():
            self._run(["shell", "input", "text", value.replace(" ", "%s")], timeout=20)
            return "已用 input text 输入（锁屏密码页）"

        _, ime_out, _ = self._run(["shell", "settings", "get", "secure", "default_input_method"])
        current = (ime_out or "").strip()
        need_ime = any(ord(ch) > 127 for ch in value) or "adbkeyboard" in current.lower()
        if not need_ime:
            self._run(["shell", "input", "text", value.replace(" ", "%s")])
            return "已输入（ASCII）"

        preferred = self._preferred_ime()
        if "adbkeyboard" not in current.lower():
            self._save_ime(current)
            preferred = current
            if skill_switch:
                self._run(["shell", "ime", "set", ADBKEYBOARD])
                time.sleep(0.4)
        self._run(["shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", value])
        time.sleep(0.4)
        if skill_switch and preferred and "adbkeyboard" not in preferred.lower():
            self._run(["shell", "ime", "set", preferred])
            time.sleep(0.2)
            return "已输入（中文，切过输入法又切回）"
        return "已输入（中文）"

    # ── 工具 ───────────────────────────────────────────
    @filter.llm_tool(name="phone_status")
    async def phone_status(self, event: AstrMessageEvent = None) -> str:
        """查看手机连接状态、型号、电量、前台应用。不需要参数。"""
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        devices = self._devices()
        if not devices:
            return json.dumps({"connected": False, "hint": "没有设备，检查 USB 调试和数据线"}, ensure_ascii=False)
        _, model, _ = self._run(["shell", "getprop", "ro.product.model"])
        _, ver, _ = self._run(["shell", "getprop", "ro.build.version.release"])
        _, size, _ = self._run(["shell", "wm", "size"])
        _, battery, _ = self._run(["shell", "dumpsys", "battery"])
        level = re.search(r"level:\s*(\d+)", battery)
        _, focus, _ = self._run(["shell", "dumpsys", "window"], timeout=20)
        app = re.search(r"mCurrentFocus=.*?([\w\.]+)/", focus)
        return json.dumps({
            "connected": True,
            "locked": self._is_locked(),
            "model": model.strip(),
            "android": ver.strip(),
            "resolution": size.strip().split(":")[-1].strip(),
            "battery": level.group(1) if level else "?",
            "foreground": app.group(1) if app else "?",
        }, ensure_ascii=False)

    @filter.llm_tool(name="phone_ui_dump")
    async def phone_ui_dump(self, event: AstrMessageEvent = None) -> str:
        """读手机当前界面的控件（文字、id、坐标）。需要知道屏幕上有哪些可点的东西时用。"""
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        ok, why = self._ensure_unlocked()
        if not ok:
            return why
        xml = self._dump()
        if not xml:
            return "读不到界面（可能锁屏了）。"
        lines = []
        for n in self._nodes(xml):
            label = n["text"] or n["desc"]
            if not label and not n["clickable"]:
                continue
            x, y = n["center"]
            lines.append(f"{label or '(无文字)'}  id={n['id'].split('/')[-1]}  点击坐标={x},{y}")
        return "\n".join(lines[:60]) or "界面没有可识别的控件。"

    @filter.llm_tool(name="phone_run")
    async def phone_run(self, event: AstrMessageEvent = None, steps: str = "[]") -> str:
        """一次跑完整段手机操作，避免反复读界面。

        Args:
            steps(string): JSON 数组，每步一个对象，支持：
                {"op":"open","query":"计算器"} 或 {"op":"open","package":"com.xx"}
                {"op":"tap","text":"发送"} 或 {"op":"tap","id":"digit_1"} 或 {"op":"tap","x":100,"y":200}
                {"op":"text","value":"中文"}   {"op":"key","key":"back"}
                {"op":"swipe","direction":"up"}  {"op":"wait","text":"成功","timeoutMs":8000}
                {"op":"sleep","ms":800}  {"op":"notify_open"} / {"op":"notify_close"}
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        if not self._devices():
            return "没有连接手机。"
        ok, why = self._ensure_unlocked()
        if not ok:
            return why + "（先用 phone_unlock 解锁，别直接点键盘）"
        try:
            plan = json.loads(steps) if isinstance(steps, str) else steps
        except Exception as exc:  # noqa: BLE001
            return f"steps 不是合法 JSON：{exc}"

        log = []
        for i, step in enumerate(plan, 1):
            op = str(step.get("op") or "")
            if op == "open":
                query = step.get("query") or ""
                package = step.get("package") or ""
                if package:
                    self._run(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
                    log.append(f"{i}. 打开 {package}")
                elif query:
                    self._run(["shell", "input", "keyevent", "KEYCODE_HOME"])
                    time.sleep(0.5)
                    self._run(["shell", "am", "start", "-a", "android.intent.action.WEB_SEARCH", "--es", "query", query])
                    log.append(f"{i}. 搜索打开 {query}")
                time.sleep(1.2)
            elif op == "tap":
                xml = self._dump()
                if step.get("x") is not None:
                    self._run(["shell", "input", "tap", str(step["x"]), str(step["y"])])
                    log.append(f"{i}. 点了坐标 {step['x']},{step['y']}")
                else:
                    ok, msg = self._tap_by(xml, text=step.get("text", ""), rid=step.get("id", ""))
                    log.append(f"{i}. {msg}")
                    if not ok:
                        texts = [n["text"] for n in self._nodes(xml) if n["text"]][:8]
                        return "\n".join(log + [f"停在第 {i} 步：界面上只有 {texts}"])
                time.sleep(0.8)
            elif op == "text":
                log.append(f"{i}. {self._type_text(str(step.get('value') or ''))}")
                time.sleep(0.6)
            elif op == "key":
                self._run(["shell", "input", "keyevent", f"KEYCODE_{str(step.get('key', 'back')).upper()}"])
                log.append(f"{i}. 按键 {step.get('key')}")
                time.sleep(0.5)
            elif op == "swipe":
                direction = step.get("direction", "up")
                cmd = {"up": "0.5 0.7 0.5 0.3", "down": "0.5 0.3 0.5 0.7",
                       "left": "0.8 0.5 0.2 0.5", "right": "0.2 0.5 0.8 0.5"}.get(direction)
                if cmd:
                    self._run(["shell", "input", "swipe", *cmd.split()])
                log.append(f"{i}. 滑动 {direction}")
                time.sleep(0.6)
            elif op == "wait":
                target = str(step.get("text") or "")
                deadline = time.time() + int(step.get("timeoutMs", 8000)) / 1000
                found = False
                while time.time() < deadline:
                    if target in self._dump():
                        found = True
                        break
                    time.sleep(0.8)
                log.append(f"{i}. 等待「{target}」{'出现' if found else '超时'}")
            elif op == "notify_open":
                self._run(["shell", "cmd", "statusbar", "expand-notifications"])
                log.append(f"{i}. 展开通知栏")
                time.sleep(0.6)
            elif op == "notify_close":
                self._run(["shell", "cmd", "statusbar", "collapse"])
                log.append(f"{i}. 收起通知栏")
            elif op == "sleep":
                time.sleep(int(step.get("ms", 800)) / 1000)
                log.append(f"{i}. 等待 {step.get('ms')}ms")
            else:
                log.append(f"{i}. 跳过未知步骤 {op}")
        return "\n".join(log)

    @filter.llm_tool(name="phone_screenshot")
    async def phone_screenshot(self, event: AstrMessageEvent = None) -> str:
        """截一张手机屏幕的图发出来。不需要参数。"""
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        if not self._devices():
            return "没有连接手机。"
        if self._is_locked():
            self._ensure_unlocked()
        else:
            self._run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
        remote = "/sdcard/_dsh_shot.png"
        local = self.base / "shot.png"
        self._run(["shell", "screencap", "-p", remote])
        self._run(["pull", remote, str(local)])
        if not local.is_file():
            return "截图失败。"
        if event is not None:
            await event.send(event.image_result(str(local)))
        return "截图已发送。"

    # ── 搜索类 ─────────────────────────────────────────
    SEARCH_APPS = {
        "pdd": ("拼多多", "com.xunmeng.pinduoduo"),
        "taobao": ("淘宝", "com.taobao.taobao"),
        "jd": ("京东", "com.jingdong.app.mall"),
    }

    def _ensure_awake(self) -> bool:
        self._run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
        self._run(["shell", "wm", "dismiss-keyguard"])
        time.sleep(0.6)
        _, focus, _ = self._run(["shell", "dumpsys", "window"], timeout=20)
        return "mCurrentFocus" in focus and "Keyguard" not in focus

    def _foreground(self) -> str:
        _, out, _ = self._run(["shell", "dumpsys", "window"], timeout=20)
        m = re.search(r"mCurrentFocus=.*?([\w\.]+)/", out)
        return m.group(1) if m else "?"

    async def _shot_and_send(self, event, name: str = "_dsh_shot.png") -> bool:
        remote = f"/sdcard/{name}"
        local = self.base / name
        self._run(["shell", "screencap", "-p", remote])
        self._run(["pull", remote, str(local)])
        if local.is_file() and event is not None:
            await event.send(event.image_result(str(local)))
            return True
        return False

    @filter.llm_tool(name="phone_search")
    async def phone_search(self, event: AstrMessageEvent = None, keyword: str = "", platform: str = "pdd") -> str:
        """在手机上搜商品（只搜不买）：打开 App → 点搜索框 → 打中文关键词 → 搜 → 截图。

        Args:
            keyword(string): 搜什么，比如「手机壳」「黑色卫衣」
            platform(string): pdd（默认拼多多）/ taobao / jd
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        keyword = (keyword or "").strip()
        if not keyword:
            return "keyword 是空的。"
        if not self._devices():
            return "没有连接手机。"
        app_name, pkg = self.SEARCH_APPS.get((platform or "pdd").lower(), self.SEARCH_APPS["pdd"])
        self._ensure_awake()
        log = [f"打开 {app_name}"]
        self._run(["shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"], timeout=25)
        time.sleep(3.0)

        xml = self._dump()
        ok = False
        for node in self._nodes(xml):
            label = node["text"] or node["desc"]
            if "搜索" in label or "搜一搜" in label:
                x, y = node["center"]
                self._run(["shell", "input", "tap", str(x), str(y)])
                log.append(f"点了搜索框「{label}」")
                ok = True
                break
        if not ok:
            log.append("没找到搜索框，可能停在了登录页或首页改版")
            await self._shot_and_send(event, "_dsh_search.png")
            return "\n".join(log)

        time.sleep(1.5)
        self._run(["shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT"])
        log.append(self._type_text(keyword))
        time.sleep(0.6)
        before = self._dump()
        tapped = False
        for node in self._nodes(before):
            if node["text"] == "搜索":
                x, y = node["center"]
                self._run(["shell", "input", "tap", str(x), str(y)])
                tapped = True
                log.append("点了「搜索」按钮")
                break
        if not tapped:
            self._run(["shell", "input", "keyevent", "66"])
            log.append("按了回车搜索")
        time.sleep(4.0)

        login_wall = any(w in self._dump() for w in ("微信登录", "手机号登录", "一键登录", "登录后"))
        await self._shot_and_send(event, "_dsh_search.png")
        fg = self._foreground()
        log.append(f"前台：{fg}")
        if login_wall:
            log.append("注意：App 停在登录页，需要先在手机上登录才能看到商品列表。")
        return "\n".join(log)

    @filter.llm_tool(name="phone_search_image")
    async def phone_search_image(self, event: AstrMessageEvent = None, path: str = "") -> str:
        """识图搜同款：把一张本机图片推给拼多多「搜图片同款」，截图结果。

        Args:
            path(string): 本机图片的绝对路径（比如消息里附件的本地路径）
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        src = Path(path or "")
        if not src.is_file():
            return f"本机找不到这个文件：{path}"
        if not self._devices():
            return "没有连接手机。"
        self._ensure_awake()
        remote = "/sdcard/Pictures/_dsh_img" + (src.suffix or ".jpg")
        code, _, err = self._run(["push", str(src), remote], timeout=60)
        if code != 0:
            return f"推图失败：{err[:120]}"
        self._run(["shell", "am", "broadcast", "-a",
                   "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote}"])
        self._run(["shell", "am", "start", "-a", "android.intent.action.SEND",
                   "-t", "image/*", "--eu", "android.intent.extra.STREAM", f"file://{remote}",
                   "-p", "com.xunmeng.pinduoduo"])
        time.sleep(5)
        await self._shot_and_send(event, "_dsh_imgsearch.png")
        return f"已把图推给拼多多识图，前台：{self._foreground()}"

    # ── 可靠性辅助 ─────────────────────────────────────
    # ── 自动解锁 ───────────────────────────────────────
    def _load_pin(self) -> str:
        """从本地文件读 PIN（不写日志、不进提示词）。文件：lock.json {"pin": "1234"}"""
        f = self.base / "lock.json"
        try:
            if f.is_file():
                data = json.loads(f.read_text(encoding="utf-8"))
                return str(data.get("pin") or "").strip()
        except Exception:
            pass
        return ""

    def _unlock(self) -> bool:
        """唤醒 + 上滑 + 输入 PIN + 回车。成功返回 True。"""
        if not self._is_locked():
            return True
        self._run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
        time.sleep(0.8)
        pin = self._load_pin()
        if not pin:
            return False
        for _ in range(2):
            self._run(["shell", "input", "swipe", "540", "2000", "540", "700", "300"])
            time.sleep(1.2)
            self._run(["shell", "input", "text", pin], timeout=20)
            time.sleep(0.6)
            self._run(["shell", "input", "keyevent", "66"])
            time.sleep(2.0)
            if not self._is_locked():
                logger.info("[phone] 已用 PIN 解锁")
                return True
            time.sleep(1.0)
        return not self._is_locked()

    def _ensure_unlocked(self) -> tuple[bool, str]:
        """需要操作时先保证解锁。返回 (是否能继续, 提示语)。"""
        if not self._is_locked():
            return True, ""
        if not self._load_pin():
            return False, "手机锁着屏，而且没配解锁密码（lock.json 里的 pin 是空的）。"
        if self._unlock():
            return True, "已自动解锁"
        return False, "手机锁着，PIN 解锁失败（可能是密码不对，或者屏幕上有别的东西挡着）。"

    def _is_locked(self) -> bool:
        """可靠的锁屏判断：只看 mDreamingLockscreen 和前台窗口名。
        注意不能简单 grep "Keyguard" —— dumpsys window 里永远有 KeyguardServiceDelegate /
        mKeyguardOccluded 这些字样，一 grep 就把「解锁状态」也判成锁屏（她之前老说锁屏就是这个）。"""
        _, out, _ = self._run(["shell", "dumpsys", "window"], timeout=25)
        flag = re.search(r"mDreamingLockscreen=(true|false)", out)
        if flag and flag.group(1) == "true":
            return True
        for pkg in re.findall(r"mCurrentFocus=Window\{[^}]*?\s([\w\.]+)/", out):
            if "keyguard" in pkg.lower():
                return True
        return False

    def _resumed_activity(self) -> str:
        _, out, _ = self._run(["shell", "dumpsys", "activity", "activities"], timeout=25)
        m = re.search(r"mResumedActivity:.*?([\w\.]+)/([\w\.$]+)", out)
        return f"{m.group(1)}/{m.group(2)}" if m else ""

    def _is_unlocked(self) -> bool:
        return not self._is_locked()

    @staticmethod
    def _looks_like_feed(cap: str) -> bool:
        return bool(cap) and ("@" in cap or "万" in cap or "点赞" in cap)

    def _wait_app_ready(self, pkg: str, timeout: float = 30) -> bool:
        """等启动画面过去（抖音在 SplashActivity 上经常卡十秒）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            act = self._resumed_activity()
            if pkg in act and "Splash" not in act and "Launcher" not in act:
                return True
            time.sleep(1.5)
        return False

    def _dump_retry(self, tries: int = 3) -> str:
        return self._dump()

    def _screencap_local(self, name: str) -> Path | None:
        remote = f"/sdcard/{name}"
        local = self.base / name
        self._run(["shell", "screencap", "-p", remote], timeout=25)
        self._run(["pull", remote, str(local)], timeout=30)
        return local if local.is_file() and local.stat().st_size > 5000 else None

    @staticmethod
    def _normalize_caption(text: str) -> str:
        """把模型偶尔吐出来的 ```json {...}``` 整理成三行纯文本。"""
        t = (text or "").strip()
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
            t = re.sub(r"\s*```$", "", t).strip()
        if t.startswith("{"):
            try:
                data = json.loads(t[t.find("{"):t.rfind("}") + 1])
                author = str(data.get("author") or data.get("作者") or "").strip()
                caption = str(data.get("caption") or data.get("文案") or "").strip()
                likes = str(data.get("likes") or data.get("点赞") or data.get("点赞数") or "").strip()
                return " ｜ ".join(x for x in (author, caption, likes) if x)
            except Exception:
                pass
        return t

    def _vision_caption(self, image: Path) -> str:
        """看不出来就让她“看”图：把截图交给 glm-4v-flash 读作者和文案。"""
        try:
            import base64
            import urllib.request
            key = str(self.cfg.get("vision_api_key") or "").strip()
            base = str(self.cfg.get("vision_api_base") or "").rstrip("/")
            model = str(self.cfg.get("vision_model") or "glm-4v-flash")
            if not key or not base:
                return ""  # 没配就跳过读图，不假装成功
            b64 = base64.b64encode(image.read_bytes()).decode("ascii")
            body = {
                "model": model,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                    {"type": "text", "text": "这是一张抖音播放页截图。只输出三行：作者（@开头的昵称）、文案（视频描述原文，没有就写无）、点赞数。不要解释。"},
                ]}],
            }
            req = urllib.request.Request(f"{base}/chat/completions",
                                         data=json.dumps(body).encode(),
                                         headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = json.loads(r.read())["choices"][0]["message"]["content"].strip()
            return self._normalize_caption(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[phone] 视觉读图失败: {exc}")
            return ""

    # ── 抖音（手机端）───────────────────────────────────
    DOUYIN_PKG = "com.ss.android.ugc.aweme"
    DOUYIN_NOISE = {"首页", "朋友", "消息", "我", "弹", "分享", "评论", "收藏",
                    "关注", "推荐", "直播", "同城", "搜索", "查看更多", "广告"}

    def _douyin_observation(self, xml: str) -> dict:
        """从一屏控件里挑出「作者 / 文案 / 点赞」这些有信息量的字。"""
        texts = []
        for node in self._nodes(xml):
            t = (node["text"] or "").strip()
            if len(t) < 4 or t in self.DOUYIN_NOISE:
                continue
            if re.fullmatch(r"[\d\.万wW]+", t):
                continue
            texts.append(t)
        seen, uniq = set(), []
        for t in texts:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        author = next((t for t in uniq if t.startswith("@")), "")
        caption = next((t for t in uniq if not t.startswith("@")), "")
        likes = next((t for t in uniq if t.endswith("万") or t.isdigit()), "")
        return {"author": author, "caption": caption, "likes": likes, "texts": uniq[:8]}

    def _remember(self, text: str) -> None:
        """把刷到的内容写进记忆库（和 QQ/抖音插件共用同一命名空间）。"""
        try:
            import urllib.request
            url = str(self.cfg.get("memory_url") or "").rstrip("/")
            ns = str(self.cfg.get("memory_ns") or "")
            if not url:
                return  # 没配记忆服务就不写
            payload = json.dumps({
                "text": text, "importance": 0.6, "source": "douyin",
                "topics": ["抖音"], "ns": ns,
            }, ensure_ascii=False).encode()
            req = urllib.request.Request(url + "/write", data=payload,
                                         headers={"Content-Type": "application/json; charset=utf-8"})
            urllib.request.urlopen(req, timeout=8).read()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[phone] 记忆写入失败: {exc}")

    @filter.llm_tool(name="phone_douyin_browse")
    async def phone_douyin_browse(self, event: AstrMessageEvent = None, count: str = "3", exit_after: str = "true") -> str:
        """用手机刷抖音：打开抖音，往下刷几条，读每条的作者和文案，最后截图。

        Args:
            count(string): 刷几条，1-8，默认 3
            exit_after(string): 刷完是否退出抖音回桌面，"true"（默认）/ "false"
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        if not self._devices():
            return "没有连接手机。"
        try:
            count = int(float(str(count or "3")))
        except Exception:
            count = 3
        count = max(1, min(8, count))
        self._ensure_awake()
        if self._is_locked():
            return "手机现在锁着屏，先解锁再让我刷。"
        self._run(["shell", "monkey", "-p", self.DOUYIN_PKG,
                   "-c", "android.intent.category.LAUNCHER", "1"], timeout=25)
        log, seen = ["打开抖音"], []
        ready, last_cap = False, ""
        for attempt in range(4):
            time.sleep(5)
            shot = self._screencap_local("_dy_probe.png")
            last_cap = self._vision_caption(shot) if shot else ""
            if self._looks_like_feed(last_cap):
                ready = True
                break
            log.append(f"第 {attempt + 1} 次查看：还没进推荐流（{last_cap[:40] or '无文字'}）")
        if not ready:
            log.append("抖音没进推荐流，先把当前画面给你看")
            await self._shot_and_send(event, "_dsh_douyin.png")
            return "\n".join(log)
        log.append("已进入推荐流")
        for i in range(count):
            # 抖音的 uiautomator 经常 dump 不出来（界面一直不 idle），直接读图更稳
            shot = self._screencap_local(f"_dy_{i}.png")
            cap = self._vision_caption(shot) if shot else ""
            if cap:
                line = f"第 {i + 1} 条：" + cap.replace("\n", " ｜ ")
                seen.append({"author": "", "caption": cap, "likes": ""})
            else:
                xml = self._dump_retry()
                obs = self._douyin_observation(xml) if xml else {"author": "", "caption": "", "likes": "", "texts": []}
                if obs["caption"] or obs["author"]:
                    line = f"第 {i + 1} 条：{obs['author']} ｜ {obs['caption'][:40]}"
                    seen.append(obs)
                else:
                    line = f"第 {i + 1} 条：没读到文字（可能是纯画面）"
            log.append(line)
            if i < count - 1:
                self._close_panels(max_back=1)   # 万一弹出评论/输入法，先关掉
                self._run(["shell", "input", "swipe", "540", "1800", "540", "500", "300"])
                time.sleep(4)

        await self._shot_and_send(event, "_dsh_douyin.png")
        if str(exit_after).lower() not in ("false", "0", "no"):
            self._run(["shell", "input", "keyevent", "KEYCODE_HOME"])
            log.append("刷完了，回桌面（抖音退到后台）")
        if seen:
            summary = "；".join(
                f"{o['author']}《{o['caption'][:30]}》" for o in seen if o["caption"]
            )
            self._remember(f"在手机抖音刷到：{summary}")
            log.append(f"已记进记忆（{len(seen)} 条）")
        return "\n".join(log)

    @filter.llm_tool(name="phone_douyin_exit")
    async def phone_douyin_exit(self, event: AstrMessageEvent = None, kill: str = "false") -> str:
        """退出抖音：回到桌面（默认）；kill="true" 则彻底关掉进程。

        Args:
            kill(string): "true" 结束进程，"false"（默认）只回桌面
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        if str(kill).lower() in ("true", "1", "yes"):
            self._run(["shell", "am", "force-stop", self.DOUYIN_PKG])
            return "抖音已关闭。"
        self._run(["shell", "input", "keyevent", "KEYCODE_HOME"])
        return "已退出抖音，回到桌面。"

    # ── 抖音：评论 / 私信 ──────────────────────────────
    def _tap_keyword(self, keywords, fallback=None) -> bool:
        """在当前界面找带这些关键词的控件并点它；找不到就用兜底坐标。"""
        xml = self._dump()
        if xml:
            for node in self._nodes(xml):
                label = f"{node['text']}{node['desc']}"
                if any(k in label for k in keywords):
                    x, y = node["center"]
                    self._run(["shell", "input", "tap", str(x), str(y)])
                    return True
        if fallback:
            self._run(["shell", "input", "tap", str(fallback[0]), str(fallback[1])])
            return True
        return False

    @filter.llm_tool(name="phone_douyin_comment")
    async def phone_douyin_comment(self, event: AstrMessageEvent = None, text: str = "") -> str:
        """在当前这条抖音视频下发一条评论（只发一条，短、口语）。

        Args:
            text(string): 评论正文，12-40 字，别抄标题、别罗列要点
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        text = (text or "").strip()
        if not text:
            return "评论内容是空的。"
        if not self._devices():
            return "没有连接手机。"
        ok, why = self._ensure_unlocked()
        if not ok:
            return why
        if not self._in_douyin():
            self._run(["shell", "monkey", "-p", self.DOUYIN_PKG,
                       "-c", "android.intent.category.LAUNCHER", "1"], timeout=25)
            time.sleep(6)
        if not self._ensure_feed():
            await self._shot_and_send(event, "_dsh_comment.png")
            return "现在不在抖音的视频页（可能在搜索页或消息页），评论取消，先回到视频再叫我。"

        allowed, used = self._comment_slot()
        if not allowed:
            return f"今天已经评了 {used} 条，够了，明天再说。"

        log = ["在视频页，准备评论"]
        # ① 点评论图标（右侧竖排第二个，坐标兜底 876,1090）
        self._tap_keyword(("评论", "comment"), fallback=(876, 1090))
        time.sleep(2.0)
        # ② 点输入框
        if not self._tap_keyword(("说点什么", "留下你的精彩", "善语结善缘", "发条评论"), fallback=(300, 2240)):
            return "找不到评论输入框，先不发了。"
        time.sleep(1.2)
        self._run(["shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT"])
        log.append(self._type_text(text))
        time.sleep(0.8)
        # ③ 点发送（兜底坐标：输入框右侧）
        if not self._tap_keyword(("发送",), fallback=(995, 2240)):
            self._run(["shell", "input", "keyevent", "66"])
            log.append("没找到发送按钮，按了回车")
        else:
            log.append("点了发送")
        time.sleep(3)
        await self._shot_and_send(event, "_dsh_comment.png")
        total = self._count_comment()
        log.append(f"今天第 {total} 条评论")
        # 关掉评论面板（否则后面上滑是在滚评论，不是换视频）
        if self._close_panels():
            log.append("已退出评论面板，回到视频页")
        else:
            log.append("没完全退出评论面板，下一条可能刷不动")
        return "\n".join(log) + "\n（截图是发出后的界面，自己确认一下有没有真的显示）"

    @filter.llm_tool(name="phone_douyin_dm")
    async def phone_douyin_dm(self, event: AstrMessageEvent = None, who: str = "", text: str = "") -> str:
        """给抖音里的某个人发私信：打开消息页 → 找到这个人 → 输入 → 发送。

        Args:
            who(string): 对方昵称（消息列表里显示的名字，尽量写全）
            text(string): 私信正文，别太长
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        who = (who or "").strip()
        text = (text or "").strip()
        if not who or not text:
            return "需要 who（对方昵称）和 text（内容）。"
        if not self._devices():
            return "没有连接手机。"
        ok, why = self._ensure_unlocked()
        if not ok:
            return why
        if not self._in_douyin():
            self._run(["shell", "monkey", "-p", self.DOUYIN_PKG,
                       "-c", "android.intent.category.LAUNCHER", "1"], timeout=25)
            time.sleep(6)

        log = [f"准备给「{who}」发私信"]
        # ① 底部「消息」
        if not self._tap_keyword(("消息",), fallback=(770, 2310)):
            return "找不到消息入口。"
        time.sleep(2.0)
        # ② 找这个人
        xml = self._dump()
        hit = False
        if xml:
            for node in self._nodes(xml):
                label = f"{node['text']}{node['desc']}"
                if who and who in label:
                    x, y = node["center"]
                    self._run(["shell", "input", "tap", str(x), str(y)])
                    hit = True
                    break
        if not hit:
            await self._shot_and_send(event, "_dsh_dm.png")
            return "\n".join(log + [f"消息列表里没找到「{who}」，截图给你看"])

        time.sleep(2.0)
        # ③ 输入框 + 发送
        if not self._tap_keyword(("发消息", "说点什么", "输入"), fallback=(400, 2240)):
            return "进了聊天页但找不到输入框。"
        time.sleep(1.0)
        self._run(["shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT"])
        log.append(self._type_text(text))
        time.sleep(0.8)
        if not self._tap_keyword(("发送",), fallback=(1000, 2240)):
            self._run(["shell", "input", "keyevent", "66"])
            log.append("没找到发送按钮，按了回车")
        else:
            log.append("点了发送")
        time.sleep(3)
        await self._shot_and_send(event, "_dsh_dm.png")
        return "\n".join(log) + "\n（截图是发出后的界面）"

    def _comment_slot(self, limit: int = 8) -> tuple[bool, int]:
        """今天还能不能评论：返回 (能不能, 今天已评几条)。"""
        import datetime as _dt
        state_file = self.base / "comments.json"
        today = _dt.date.today().isoformat()
        try:
            data = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else {}
        except Exception:
            data = {}
        if data.get("date") != today:
            data = {"date": today, "count": 0}
        used = int(data.get("count", 0))
        return used < limit, used

    def _count_comment(self) -> int:
        import datetime as _dt
        state_file = self.base / "comments.json"
        today = _dt.date.today().isoformat()
        try:
            data = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else {}
        except Exception:
            data = {}
        if data.get("date") != today:
            data = {"date": today, "count": 0}
        data["count"] = int(data.get("count", 0)) + 1
        state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data["count"]

    def _close_panels(self, max_back: int = 3) -> bool:
        """把评论面板、输入法、弹窗之类的弹层关掉，回到视频页。
        评论区挡住时上滑是滚评论，不是换视频——之前就是卡在这里。"""
        for _ in range(max_back):
            shot = self._screencap_local("_panel_check.png")
            cap = self._vision_caption(shot) if shot else ""
            # 视频页特征：有作者/点赞；评论面板特征：有"发送"/"说点什么"/大量"回复"
            if self._looks_like_feed(cap) and "发送" not in cap:
                return True
            self._run(["shell", "input", "keyevent", "KEYCODE_BACK"])
            time.sleep(1.5)
        shot = self._screencap_local("_panel_check.png")
        cap = self._vision_caption(shot) if shot else ""
        return self._looks_like_feed(cap) and "发送" not in cap

    def _ensure_feed(self, tries: int = 3) -> bool:
        """确保当前是「视频推荐流」页面。搜索页/消息页/个人页都不是，先退出去。
        之前评论发错，就是因为手机停在抖音搜索页，文字打进了搜索框。"""
        for _ in range(tries):
            shot = self._screencap_local("_feed_check.png")
            cap = self._vision_caption(shot) if shot else ""
            if self._looks_like_feed(cap):
                return True
            # 不是推荐流：先按返回；返回没用就重开抖音
            self._run(["shell", "input", "keyevent", "KEYCODE_BACK"])
            time.sleep(1.5)
            if not self._in_douyin():
                self._run(["shell", "monkey", "-p", self.DOUYIN_PKG,
                           "-c", "android.intent.category.LAUNCHER", "1"], timeout=25)
                time.sleep(6)
        shot = self._screencap_local("_feed_check.png")
        cap = self._vision_caption(shot) if shot else ""
        return self._looks_like_feed(cap)

    def _in_douyin(self) -> bool:
        act = self._resumed_activity()
        return self.DOUYIN_PKG in act

    # ── B站（手机端）──────────────────────────────────
    BILI_PKG = "tv.danmaku.bili"
    BILI_MARKERS = ("弹幕", "播放", "点赞", "投币", "收藏", "UP主", "关注", "万")

    def _looks_like_bili(self, cap: str) -> bool:
        return bool(cap) and any(m in cap for m in self.BILI_MARKERS)

    def _ensure_bili_feed(self, tries: int = 3) -> bool:
        for _ in range(tries):
            shot = self._screencap_local("_bili_check.png")
            cap = self._vision_caption(shot) if shot else ""
            if self._looks_like_bili(cap):
                return True
            self._run(["shell", "input", "keyevent", "KEYCODE_BACK"])
            time.sleep(1.5)
            if self.BILI_PKG not in self._resumed_activity():
                self._run(["shell", "monkey", "-p", self.BILI_PKG,
                           "-c", "android.intent.category.LAUNCHER", "1"], timeout=25)
                time.sleep(6)
        shot = self._screencap_local("_bili_check.png")
        return self._looks_like_bili(self._vision_caption(shot) if shot else "")

    @filter.llm_tool(name="phone_bili_browse")
    async def phone_bili_browse(self, event: AstrMessageEvent = None, count: str = "3", exit_after: str = "true") -> str:
        """用手机刷 B站：打开 B站 推荐，往下刷几条，读标题和 UP 主，最后截图。

        Args:
            count(string): 刷几条，1-8，默认 3
            exit_after(string): 刷完是否回桌面，"true"（默认）/ "false"
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        if not self._devices():
            return "没有连接手机。"
        ok, why = self._ensure_unlocked()
        if not ok:
            return why
        try:
            count = max(1, min(8, int(float(str(count or "3")))))
        except Exception:
            count = 3

        self._run(["shell", "monkey", "-p", self.BILI_PKG,
                   "-c", "android.intent.category.LAUNCHER", "1"], timeout=25)
        log, seen = ["打开 B站"], []
        ready = False
        for attempt in range(4):
            time.sleep(5)
            shot = self._screencap_local("_bili_probe.png")
            cap = self._vision_caption(shot) if shot else ""
            if self._looks_like_bili(cap):
                ready = True
                break
            log.append(f"第 {attempt + 1} 次查看：还没进 B站 推荐（{cap[:30] or '无文字'}）")
        if not ready:
            await self._shot_and_send(event, "_dsh_bili.png")
            return "\n".join(log + ["B站 没进推荐流，先把当前画面给你看"])

        log.append("已进入 B站 推荐")
        for i in range(count):
            shot = self._screencap_local(f"_bili_{i}.png")
            cap = self._vision_caption(shot) if shot else ""
            if cap:
                log.append(f"第 {i + 1} 条：" + cap.replace("\n", " ｜ "))
                seen.append(cap)
            else:
                log.append(f"第 {i + 1} 条：没读到文字")
            if i < count - 1:
                self._close_panels(max_back=1)   # 万一弹出评论/输入法，先关掉
                self._run(["shell", "input", "swipe", "540", "1800", "540", "500", "300"])
                time.sleep(4)

        await self._shot_and_send(event, "_dsh_bili.png")
        if str(exit_after).lower() not in ("false", "0", "no"):
            self._run(["shell", "input", "keyevent", "KEYCODE_HOME"])
            log.append("刷完了，回桌面")
        if seen:
            self._remember("在手机 B站 刷到：" + "；".join(s[:40] for s in seen[:3]))
            log.append(f"已记进记忆（{len(seen)} 条）")
        return "\n".join(log)

    @filter.llm_tool(name="phone_bili_comment")
    async def phone_bili_comment(self, event: AstrMessageEvent = None, text: str = "") -> str:
        """在当前这条 B站 视频下发一条评论（短、口语，只发一条）。

        Args:
            text(string): 评论正文
        """
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        text = (text or "").strip()
        if not text:
            return "评论内容是空的。"
        if not self._devices():
            return "没有连接手机。"
        ok, why = self._ensure_unlocked()
        if not ok:
            return why
        if self.BILI_PKG not in self._resumed_activity():
            self._run(["shell", "monkey", "-p", self.BILI_PKG,
                       "-c", "android.intent.category.LAUNCHER", "1"], timeout=25)
            time.sleep(6)
        if not self._ensure_bili_feed():
            await self._shot_and_send(event, "_dsh_bili.png")
            return "现在不在 B站 的视频页，评论取消。"

        log = ["在 B站 视频页，准备评论"]
        if not self._tap_keyword(("评论", "写评论", "说点什么"), fallback=(980, 1560)):
            return "找不到评论入口，先不发了。"
        time.sleep(2.0)
        if not self._tap_keyword(("发个友善的弹幕", "说点什么", "善语结善缘", "评论"), fallback=(300, 2240)):
            return "找不到评论输入框。"
        time.sleep(1.0)
        self._run(["shell", "am", "broadcast", "-a", "ADB_CLEAR_TEXT"])
        log.append(self._type_text(text))
        time.sleep(0.8)
        if not self._tap_keyword(("发送",), fallback=(1000, 2240)):
            self._run(["shell", "input", "keyevent", "66"])
            log.append("按了回车发送")
        else:
            log.append("点了发送")
        time.sleep(3)
        await self._shot_and_send(event, "_dsh_bili_comment.png")
        self._run(["shell", "input", "keyevent", "KEYCODE_BACK"])
        return "\n".join(log) + "\n（截图是发出后的界面）"

    @filter.llm_tool(name="phone_unlock")
    async def phone_unlock(self, event: AstrMessageEvent = None) -> str:
        """解锁手机（用本地配置的 PIN）。锁屏时先调这个，不要用 phone_run 去点键盘。不需要参数。"""
        if event is not None and not self._allowed(event):
            return "没有权限操作手机。"
        if not self._devices():
            return "没有连接手机。"
        if not self._is_locked():
            return "手机没锁，已经是解锁状态。"
        if not self._load_pin():
            return "没配解锁密码（lock.json 的 pin 是空的）。"
        ok = self._unlock()
        if ok:
            self._run(["shell", "input", "keyevent", "KEYCODE_HOME"])
            return "已解锁（用 PIN），回到桌面了。"
        return "PIN 解锁失败：可能密码不对，或者锁屏上弹了别的窗口挡着。"

    # ── 命令（调试用）──────────────────────────────────
    @filter.command("刷抖音")
    async def cmd_douyin(self, event: AstrMessageEvent):
        """刷抖音：/刷抖音 [条数] —— 直接跑一遍，方便排查"""
        raw = (event.message_str or "").strip()
        arg = raw.split(" ", 1)[1].strip() if " " in raw else "3"
        yield event.plain_result(await self.phone_douyin_browse(event, arg))

    @filter.command("手机状态")
    async def cmd_status(self, event: AstrMessageEvent):
        yield event.plain_result(await self.phone_status(event))
