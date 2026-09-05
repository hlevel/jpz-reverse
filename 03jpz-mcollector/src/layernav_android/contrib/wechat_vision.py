"""OpenCV primitives for WeChat screen recognition.

The detector is template-driven because WeChat pages often expose no useful
accessibility text. Templates are optional; when absent, callers can use the
detector's ``None`` result and keep the workflow paused safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class TemplateMatch:
    """Location and confidence of one template match."""

    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


def decode_png(data: bytes) -> np.ndarray:
    """Decode ADB PNG bytes and reject malformed frames."""
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError("invalid screenshot PNG")
    return image


class WeChatVision:
    """Template matcher with resolution-independent confidence thresholds."""

    def __init__(self, template_dir: str | Path = "config/templates", threshold: float = 0.82) -> None:
        self.template_dir = Path(template_dir)
        self.threshold = float(threshold)

    def load_template(self, name: str) -> np.ndarray | None:
        """Load ``name`` from the configured directory, or return ``None``."""
        path = self.template_dir / name
        if not path.is_file():
            return None
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        return image if image is not None and image.size else None

    @staticmethod
    def has_wechat_home_navigation(frame: np.ndarray) -> bool:
        """Detect the selected green WeChat tab in the lower-left navigation.

        The standard WeChat conversation home shows a saturated green icon and
        label in this area. Search pages and the pulled-down mini-program
        panel do not, so this supplies a stable homepage signal before a
        user-provided full-page template exists.
        """
        if frame is None or frame.size == 0:
            return False
        height, width = frame.shape[:2]
        # Exclude the system navigation strip and inspect only tab one.
        region = frame[int(height * 0.78):int(height * 0.96), :int(width * 0.25)]
        if region.size == 0:
            return False
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(hsv, (35, 100, 80), (95, 255, 255))
        return int(cv2.countNonZero(green)) >= max(80, region.size // 400)

    def match(
        self,
        frame: np.ndarray,
        template: np.ndarray | None,
        *,
        threshold: float | None = None,
    ) -> TemplateMatch | None:
        """Find the best match across screenshot and template scale changes.

        Templates may be cropped from a desktop preview rather than the native
        ADB screenshot.  The wider range accommodates that common difference;
        callers retain the normal strict confidence threshold unless a known
        low-detail template explicitly supplies a different one.
        """
        if template is None or frame.size == 0:
            return None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        templ_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        best: TemplateMatch | None = None
        for scale in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0):
            width = max(8, round(templ_gray.shape[1] * scale))
            height = max(8, round(templ_gray.shape[0] * scale))
            if width >= gray.shape[1] or height >= gray.shape[0]:
                continue
            resized = cv2.resize(templ_gray, (width, height), interpolation=cv2.INTER_AREA)
            scores = cv2.matchTemplate(gray, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(scores)
            candidate = TemplateMatch(location[0], location[1], width, height, float(score))
            if best is None or candidate.confidence > best.confidence:
                best = candidate
        minimum_confidence = self.threshold if threshold is None else float(threshold)
        return best if best and best.confidence >= minimum_confidence else None
