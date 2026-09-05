"""WeChat-hosted Meituan mini-program task model."""

from __future__ import annotations

import time
from enum import Enum
import re

from layernav_android._protocol import AdbProtocol
from layernav_android.base import BaseLayerModel, LayerDef
from layernav_android.config.models import TaskConfig
from layernav_android.contrib.wechat import WECHAT_PACKAGE
from layernav_android.cold_start import cold_start_app_from_launcher
from layernav_android.logging import get_logger
from layernav_android.contrib.wechat_vision import WeChatVision, TemplateMatch, decode_png

logger = get_logger(__name__)


class WeChatPage(str, Enum):
    """Coarse page states used before a mini-program search begins."""

    PHONE = "phone"
    WECHAT = "wechat"
    MINI_PROGRAM_PANEL = "mini_program_panel"
    UNKNOWN = "unknown"


class WeChatMeituanLayerModel(BaseLayerModel):
    """Route to WeChat's mini-program search field without running a task."""

    def __init__(self, template_dir: str = "config/templates") -> None:
        super().__init__()
        self.vision = WeChatVision(template_dir)

    layers = [
        LayerDef("L0", "home", "手机桌面", "foreground is not WeChat"),
        LayerDef("L1", "wechat", "微信页面", "WeChat foreground"),
        LayerDef("L2", "meituan", "美团小程序", "Meituan mini-program page"),
        LayerDef("L3", "task", "美团任务页面", "Meituan task page"),
    ]

    def detect(self, adb: AdbProtocol, scale_w: float) -> str | None:
        """Classify desktop, recognized WeChat home, or recognized Meituan."""
        page = self.detect_page(adb)
        if page == WeChatPage.PHONE:
            return "L0"
        if page == WeChatPage.MINI_PROGRAM_PANEL:
            return "L2"
        if page == WeChatPage.WECHAT:
            return "L1"
        return None

    def detect_layer(self, adb: AdbProtocol, scale_w: float, layer: str) -> bool:
        """Target-aware check using package state and page-specific templates."""
        page = self.detect_page(adb)
        if layer == "L0":
            return page == WeChatPage.PHONE
        if layer == "L1":
            return page == WeChatPage.WECHAT
        if layer == "L2":
            return page == WeChatPage.MINI_PROGRAM_PANEL
        return False

    def run_task(self, adb: AdbProtocol, task: TaskConfig) -> bool:
        """Perform the current navigation milestone and never claim a task."""
        opened = self.open_mini_program_search(adb)
        logger.info("mini_program_search_opened", opened=opened)
        if opened:
            searched = self.search_meituan_takeout(adb)
            logger.info("meituan_takeout_search_submitted", searched=searched)
        # Entering a result list is navigation only; later task work decides success.
        return False

    def detect_page(self, adb: AdbProtocol) -> WeChatPage:
        """Classify phone, WeChat, or the image-recognized panel.

        The ``搜索小程序`` template is the positive panel signal. ADB or
        screenshot errors are unknown, which forces safe recovery instead of
        a blind gesture or click.
        """
        try:
            if adb.foreground_package() != WECHAT_PACKAGE:
                return WeChatPage.PHONE
            if self._match_template(adb, "search_box.png") is not None:
                return WeChatPage.MINI_PROGRAM_PANEL
            # A package check alone is not enough: Android can restore a
            # prior WeChat search, chat, or mini-program page on launch.
            if self._has_wechat_home_navigation(adb):
                return WeChatPage.WECHAT
            return WeChatPage.UNKNOWN
        except Exception:
            logger.warning("wechat_page_detection_failed", exc_info=True)
            return WeChatPage.UNKNOWN

    def open_mini_program_search(self, adb: AdbProtocol) -> bool:
        """Wake and route ``phone -> WeChat -> panel -> search box``.

        If the expected page cannot be recognized, HOME is pressed so the next
        scheduler attempt has a deterministic starting point.
        """
        # Do not swipe an already unlocked device: on gesture-navigation ROMs
        # that swipe could leave WeChat. Wake-and-unlock is only needed when
        # Android reports an active keyguard.
        if hasattr(adb, "is_locked") and adb.is_locked():
            if not adb.wake_and_unlock():
                logger.warning("device_unlock_failed")
                return False

        # A normal run always starts from Android HOME. This keeps a restored
        # WeChat activity from skipping the requested phone -> WeChat route.
        self._return_to_phone(adb)
        if not self._enter_wechat_from_phone(adb):
            return False
        if not self._enter_wechat_home(adb):
            self._return_to_phone(adb)
            return False

        # The first frame after the gesture can still be WeChat's home
        # animation. Poll briefly, then retry the gesture once if needed.
        page = WeChatPage.UNKNOWN
        for _ in range(2):
            adb.swipe(540, 320, 540, 1750, duration_ms=600)
            for _ in range(6):
                time.sleep(0.35)
                page = self.detect_page(adb)
                if page == WeChatPage.MINI_PROGRAM_PANEL:
                    break
            if page == WeChatPage.MINI_PROGRAM_PANEL:
                break

        if page != WeChatPage.MINI_PROGRAM_PANEL:
            logger.warning("mini_program_panel_not_recognized", page=page.value)
            self._return_to_phone(adb)
            return False

        if self._click_template_stable(adb, "search_box.png"):
            return True
        logger.warning("mini_program_search_box_not_recognized")
        self._return_to_phone(adb)
        return False

    @staticmethod
    def _return_to_phone(adb: AdbProtocol) -> None:
        """Recover from an unsupported page state by returning HOME."""
        adb.key_event(3)  # KEYCODE_HOME
        time.sleep(0.8)

    @staticmethod
    def _enter_wechat_from_phone(adb: AdbProtocol) -> bool:
        """Launch WeChat from the phone page without task-specific actions."""
        return cold_start_app_from_launcher(
            adb, WECHAT_PACKAGE, app_name="wechat", M=4, N=3,
            force_stop_before=False,
        )

    def _enter_wechat_home(self, adb: AdbProtocol) -> bool:
        """Return from a restored subpage and select the conversation tab.

        WeChat restores its last activity after launch. BACK is bounded while
        the green lower-left tab is the positive signal that the main tab bar
        has been reached and can safely be selected.
        """
        for _ in range(3):
            if adb.foreground_package() != WECHAT_PACKAGE:
                return False
            if self._has_wechat_home_navigation(adb):
                frame = decode_png(adb.capture_png() if hasattr(adb, "capture_png") else adb.screencap())
                height, width = frame.shape[:2]
                adb.tap(int(width * 0.10), int(height * 0.92))
                time.sleep(0.7)
                # The selected tab can repaint briefly after the tap. The
                # positive pre-tap navigation signal is sufficient here; the
                # following mini-program-panel template remains the gate.
                return True
            # A panel or search page returns to the main tab bar via BACK.
            adb.key_event(4)  # KEYCODE_BACK
            time.sleep(0.7)
        return False

    def _match_template(self, adb: AdbProtocol, name: str) -> TemplateMatch | None:
        """Capture one frame and locate a configured template."""
        template = self.vision.load_template(name)
        if template is None:
            return None
        # A search-box crop can contain only its small placeholder text, so it
        # has less visual context than an application icon.  It uses a modestly
        # lower threshold; all result and icon templates remain strict.
        threshold = 0.75 if name == "search_box.png" else None
        frame = decode_png(adb.capture_png() if hasattr(adb, "capture_png") else adb.screencap())
        return self.vision.match(frame, template, threshold=threshold)

    def _has_wechat_home_navigation(self, adb: AdbProtocol) -> bool:
        """Check the current screenshot for WeChat's selected home tab."""
        frame = decode_png(adb.capture_png() if hasattr(adb, "capture_png") else adb.screencap())
        return self.vision.has_wechat_home_navigation(frame)

    def _click_template_stable(self, adb: AdbProtocol, name: str, frames: int = 2) -> bool:
        """Require the same template to appear in consecutive frames."""
        last: TemplateMatch | None = None
        stable = 0
        for _ in range(frames + 1):
            current = self._match_template(adb, name)
            if current is not None and last is not None:
                drift = abs(current.x - last.x) + abs(current.y - last.y)
                stable = stable + 1 if drift <= max(12, current.width // 5) else 0
            elif current is not None:
                stable = 1
            else:
                stable = 0
            last = current
            if stable >= frames and current is not None:
                adb.tap(*current.center)
                time.sleep(0.6)
                return True
            time.sleep(0.25)
        return False

    def focus_search_input(self, adb: AdbProtocol) -> bool:
        """Focus the mini-program search input via UI first, then OpenCV."""
        # UIAutomator is the lower-cost and less device-specific option when
        # a WeChat build actually exposes a real editable node.
        if self._click_ui_node(adb, text="搜索", require_editable=True):
            return True
        # This WeChat build exposes only an empty XML root, so match the two
        # placeholder characters cropped from the real device screenshot.
        return self._click_template_stable(adb, "search_input_text.png")

    def click_search_button(self, adb: AdbProtocol) -> bool:
        """Click the green search button via UI first, then OpenCV."""
        if self._click_ui_node(adb, text="搜索", require_clickable=True):
            return True
        return self._click_template_stable(adb, "search_button.png")

    def search_meituan_takeout(self, adb: AdbProtocol) -> bool:
        """Search ``美团外卖`` through the virtual keyboard and open result one.

        This is used because the connected Android build supports neither the
        ADB clipboard service nor direct Unicode ``input text`` injection.
        The input method's first candidate is selected after entering the full
        pinyin, then the result-list's first row is opened after submission.
        """
        if not self.focus_search_input(adb):
            return False
        if not self._tap_pinyin_on_virtual_keyboard(adb, "meituanwaimai"):
            return False
        # The first IME candidate is not guaranteed to be the target phrase.
        # Only an exact visual template may authorize selecting it.
        if not self._click_template_stable(adb, "meituan_takeout_candidate.png"):
            return False
        if not self.click_search_button(adb):
            return False
        time.sleep(2.0)
        return self._tap_first_search_result(adb)

    @staticmethod
    def _tap_first_search_result(adb: AdbProtocol) -> bool:
        """Open the first result row below the persistent search header."""
        try:
            frame = decode_png(adb.capture_png() if hasattr(adb, "capture_png") else adb.screencap())
        except Exception:
            return False
        height, width = frame.shape[:2]
        adb.tap(round(width * 0.50), round(height * 0.16))
        time.sleep(1.0)
        return True

    @staticmethod
    def _tap_pinyin_on_virtual_keyboard(adb: AdbProtocol, text: str) -> bool:
        """Tap a QWERTY IME using positions relative to its screenshot size."""
        try:
            frame = decode_png(adb.capture_png() if hasattr(adb, "capture_png") else adb.screencap())
        except Exception:
            return False
        height, width = frame.shape[:2]
        # Xiaomi's standard QWERTY IME: row 1 has 10 keys, row 2 has 9,
        # and row 3 has Z-X-C-V-B-N-M. Ratios survive native resolution changes.
        keys = {
            "q": (0.05, 0.696), "w": (0.15, 0.696), "e": (0.25, 0.696),
            "r": (0.35, 0.696), "t": (0.45, 0.696), "y": (0.55, 0.696),
            "u": (0.65, 0.696), "i": (0.75, 0.696), "o": (0.85, 0.696),
            "p": (0.95, 0.696), "a": (0.10, 0.767), "s": (0.20, 0.767),
            "d": (0.30, 0.767), "f": (0.40, 0.767), "g": (0.50, 0.767),
            "h": (0.60, 0.767), "j": (0.70, 0.767), "k": (0.80, 0.767),
            "l": (0.90, 0.767), "z": (0.19, 0.833), "x": (0.29, 0.833),
            "c": (0.39, 0.833), "v": (0.49, 0.833), "b": (0.59, 0.833),
            "n": (0.69, 0.833), "m": (0.79, 0.833),
        }
        for char in text.lower():
            point = keys.get(char)
            if point is None:
                return False
            adb.tap(round(width * point[0]), round(height * point[1]))
            time.sleep(0.08)
        time.sleep(0.5)
        return True

    @staticmethod
    def _dump_ui(adb: AdbProtocol) -> str:
        """Read UIAutomator XML; unsupported pages return an empty document."""
        try:
            adb._run(["shell", "uiautomator", "dump", "/sdcard/window.xml"])
            return adb._run(["shell", "cat", "/sdcard/window.xml"])
        except Exception:
            return ""

    def _click_ui_node(
        self,
        adb: AdbProtocol,
        *,
        text: str,
        require_editable: bool = False,
        require_clickable: bool = False,
    ) -> bool:
        """Click a matching UI node only when it satisfies its expected role."""
        for node in re.finditer(r"<node\b[^>]*>", self._dump_ui(adb)):
            attributes = node.group(0)
            if text not in attributes:
                continue
            lower = attributes.lower()
            if require_editable and "edittext" not in lower:
                continue
            if require_clickable and 'clickable="true"' not in lower:
                continue
            bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', attributes)
            if bounds is None:
                continue
            x1, y1, x2, y2 = map(int, bounds.groups())
            adb.tap((x1 + x2) // 2, (y1 + y2) // 2)
            time.sleep(0.5)
            return True
        return False

    def _on_L0(self, adb, scale_w, *, quick=False): return None
    def _on_L1(self, adb, scale_w, *, quick=False): return None
    def _on_L2(self, adb, scale_w, *, quick=False): return None
    def _on_L3(self, adb, scale_w, *, quick=False): return None
