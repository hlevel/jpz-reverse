"""WeChat-hosted Ctrip mini-program task model."""

from __future__ import annotations

from layernav_android._protocol import AdbProtocol
from layernav_android.base import BaseLayerModel, LayerDef
from layernav_android.config.models import TaskConfig
from layernav_android.contrib.wechat import WECHAT_PACKAGE
from layernav_android.cold_start import cold_start_app_from_launcher


class WeChatCtripLayerModel(BaseLayerModel):
    """Navigation skeleton for Ctrip; UI recognition is added incrementally."""

    layers = [
        LayerDef("L0", "home", "手机桌面", "foreground is not WeChat"),
        LayerDef("L1", "wechat", "微信页面", "WeChat foreground"),
        LayerDef("L2", "ctrip", "携程小程序", "Ctrip mini-program page"),
        LayerDef("L3", "task", "携程任务页面", "Ctrip task page"),
    ]

    def detect(self, adb: AdbProtocol, scale_w: float) -> str:
        """Return L0 until real WeChat/Ctrip recognition is implemented."""
        return "L0"

    def detect_layer(self, adb: AdbProtocol, scale_w: float, layer: str) -> bool:
        """Conservative placeholder target check; never claims task arrival."""
        return layer == "L0"

    def run_task(self, adb: AdbProtocol, task: TaskConfig) -> bool:
        """Start WeChat; task API and mini-program entry are separate hooks."""
        if adb.foreground_package() != WECHAT_PACKAGE:
            cold_start_app_from_launcher(adb, WECHAT_PACKAGE, app_name="wechat", M=4, N=3)
        return False

    def _on_L0(self, adb, scale_w, *, quick=False): return None
    def _on_L1(self, adb, scale_w, *, quick=False): return None
    def _on_L2(self, adb, scale_w, *, quick=False): return None
    def _on_L3(self, adb, scale_w, *, quick=False): return None
