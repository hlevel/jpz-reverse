"""Windows WeChat mini-program UI automation.

This module operates only the visible, already authenticated WeChat desktop UI.
It does not read or create private WeChat protocol credentials.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import mss
import numpy as np
import pyautogui
from paddleocr import PaddleOCR
from pywinauto import Desktop


ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger("wxpc_xcxauto")


@dataclass
class WindowBounds:
    left: int
    top: int
    width: int
    height: int


class WeChatMiniProgramAutomation:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.timeout = float(config.get("default_timeout_seconds", 15))
        self.screenshot_dir = ROOT / config.get("screenshots_dir", "artifacts/screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        self.bounds: WindowBounds | None = None

    def connect_wechat(self) -> None:
        title = self.config.get("wechat_window_title", "微信")
        try:
            window = Desktop(backend="uia").window(title_re=rf".*{title}.*")
            window.wait("visible", timeout=self.timeout)
            if window.is_minimized():
                window.restore()
            window.set_focus()
            rect = window.rectangle()
            self.bounds = WindowBounds(rect.left, rect.top, rect.width(), rect.height())
        except Exception as exc:
            raise RuntimeError("未找到已登录的微信窗口，请先在 Windows 微信上完成正常登录。") from exc

    def open_mini_program(self) -> None:
        name = self.config.get("mini_program_name", "").strip()
        if not name:
            raise ValueError("config.json 的 mini_program_name 不能为空。")
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.5)
        pyautogui.write(name)
        time.sleep(1)
        pyautogui.press("enter")
        time.sleep(float(self.config.get("startup_wait_seconds", 2)))

    def capture(self) -> np.ndarray:
        if self.bounds is None:
            raise RuntimeError("微信窗口尚未连接。")
        monitor = {
            "left": self.bounds.left,
            "top": self.bounds.top,
            "width": self.bounds.width,
            "height": self.bounds.height,
        }
        with mss.mss() as screen:
            image = np.array(screen.grab(monitor))
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    def screenshot(self, name: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self.screenshot_dir / f"{stamp}-{name}.png"
        cv2.imwrite(str(target), self.capture())
        LOGGER.info("截图已保存：%s", target)
        return target

    def find_text(self, expected: str) -> tuple[int, int] | None:
        image = self.capture()
        result = self.ocr.ocr(image, cls=True)
        for block in result or []:
            for line in block or []:
                points, (text, _confidence) = line
                if expected in text:
                    x = int(sum(point[0] for point in points) / len(points))
                    y = int(sum(point[1] for point in points) / len(points))
                    return x, y
        return None

    def find_template(self, template_path: str, threshold: float = 0.88) -> tuple[int, int] | None:
        template = cv2.imread(str(ROOT / template_path))
        if template is None:
            raise FileNotFoundError(f"模板不存在：{template_path}")
        result = cv2.matchTemplate(self.capture(), template, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(result)
        if score < threshold:
            return None
        return point[0] + template.shape[1] // 2, point[1] + template.shape[0] // 2

    def click_relative(self, x: float, y: float) -> None:
        if self.bounds is None:
            raise RuntimeError("微信窗口尚未连接。")
        pyautogui.click(self.bounds.left + int(self.bounds.width * x), self.bounds.top + int(self.bounds.height * y))

    def wait_until(self, finder: Any, timeout: float) -> tuple[int, int]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            position = finder()
            if position:
                return position
            time.sleep(0.5)
        raise TimeoutError("等待页面元素超时。")

    def run_action(self, action: dict[str, Any]) -> None:
        action_type = action["type"]
        timeout = float(action.get("timeout_seconds", self.timeout))
        if action_type == "wait":
            time.sleep(float(action["seconds"]))
        elif action_type == "screenshot":
            self.screenshot(action.get("name", "manual"))
        elif action_type == "click_relative":
            self.click_relative(float(action["x"]), float(action["y"]))
        elif action_type in {"wait_for_text", "click_text"}:
            position = self.wait_until(lambda: self.find_text(action["text"]), timeout)
            if action_type == "click_text":
                pyautogui.click(self.bounds.left + position[0], self.bounds.top + position[1])
        elif action_type == "click_template":
            position = self.wait_until(
                lambda: self.find_template(action["template"], float(action.get("threshold", 0.88))),
                timeout,
            )
            pyautogui.click(self.bounds.left + position[0], self.bounds.top + position[1])
        else:
            raise ValueError(f"不支持的动作类型：{action_type}")

    def run(self) -> None:
        self.connect_wechat()
        self.open_mini_program()
        for index, action in enumerate(self.config.get("actions", []), start=1):
            LOGGER.info("执行第 %d 步：%s", index, action["type"])
            self.run_action(action)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows 微信小程序可见界面自动化")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        WeChatMiniProgramAutomation(load_config(args.config)).run()
    except Exception as exc:
        LOGGER.exception("自动化失败：%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
