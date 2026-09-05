"""Focused tests for the OpenCV template matching helper."""

from __future__ import annotations

import cv2
import numpy as np

from layernav_android.contrib.wechat_vision import WeChatVision


def test_match_supports_a_template_cropped_at_smaller_scale(tmp_path):
    """A desktop-cropped template can still match a native-size screenshot."""
    template = np.zeros((20, 80, 3), dtype=np.uint8)
    cv2.putText(template, "find", (2, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    native_crop = cv2.resize(template, (200, 50), interpolation=cv2.INTER_CUBIC)
    frame = np.zeros((500, 500, 3), dtype=np.uint8)
    frame[120:170, 180:380] = native_crop

    match = WeChatVision(tmp_path).match(frame, template, threshold=0.7)

    assert match is not None
    assert abs(match.x - 180) <= 2
    assert abs(match.y - 120) <= 2
    assert match.width == 200
    assert match.height == 50
