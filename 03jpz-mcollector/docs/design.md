# 运行框架设计

## 目标

配置驱动多设备采集。一个设备由一个线程控制，同一设备内的多个账号串行执行；不同设备之间并行执行。

## 配置关系

`sdk_path` 指向 Android SDK 根目录，设备管理器自动拼接
`platform-tools/adb.exe`。设备可通过 `serial` 指定具体真机或模拟器。

设备探测时会调用 `wake_and_unlock()`：发送唤醒按键、尝试系统解锁并向上滑动。该能力只适用于
无凭据锁屏，不能绕过 PIN、密码、图案、生物识别或任何其他锁屏保护。

`devices[*].accounts.<name>` 使用同名匹配到 `tasks.<name>`，账号的 `rule` 字段匹配 `rules[].name`。加载器在启动阶段拒绝缺失任务、缺失规则和非法时间范围。

## 启动流程

```text
load_config -> 校验配置 -> DeviceManager 过滤启用设备
    -> 创建 SubprocessAdb -> get-state 检查在线
    -> TaskRunner.run_all
```

命令行入口为 `layernav-android`，默认读取 `config/config.yaml`。在业务模型接入前可使用
`uv run layernav-android --check`，只加载配置并探测 ADB 设备，不执行页面操作。

设备相关日志统一以设备名为前缀，例如 `[android-device-01] adb: online`，便于多设备并行时区分输出。

## 线程模型

`run_all()` 为每台启用设备提交一个线程任务。线程内部调用 `run_device()`，按配置顺序串行处理该设备账号，避免多个线程同时向同一 ADB 会话发送输入事件。`max_workers` 用于限制设备并发数。

## 单设备运行

```text
创建/取得设备 ADB 会话
  -> 遍历启用账号
  -> 账号名查找任务，rule 查找规则
  -> model.init(adb)
  -> 重复调用 model.run_task(adb, task)
  -> 成功计数，按规则休息，达到 max_tasks 后结束
```

页面识别、冷启动、点击校验和故障恢复仍由 `BaseLayerModel` 及其业务子类负责；运行器不直接操作页面。

## 微信小程序入口

### 美团入口状态路由

美团当前入口严格按以下顺序执行：唤醒并解锁（仅在锁屏时） -> 判断当前页面
（手机页、微信页、小程序面板） -> 手机页启动微信 -> 微信页执行一次下拉手势
打开小程序面板 -> 截图并用 OpenCV 匹配 `搜索小程序` -> 连续帧确认后点击搜索框。
页面识别失败或面板无法确认时按 HOME 返回手机页，不输入搜索词，也不盲目点击。
搜索词、搜索结果、美团小程序页面以及任务 API 属于后续阶段。

`wechat_ctrip.py` 和 `wechat_meituan.py` 共用微信宿主能力：先确认微信前台，必要时调用
`cold_start_app_from_launcher()` 冷启动微信，再通过 Android `VIEW` Intent 打开配置中的
`claim_url`。后续页面识别成功后，`run_task()` 才返回成功并进入任务计数；当前模型仍是入口骨架，
不会伪报任务完成。

美团入口不使用 `claim_url`。模型先在微信主页下拉打开小程序面板，通过 UIAutomator XML 查找
名称包含“美团”或“meituan”的节点并点击；未发现时，定位搜索输入框，输入 `meituan` 后再次查找
并点击结果。进入小程序仅属于任务准备阶段，尚未领取或完成任务。

当微信不暴露可访问节点时，入口流程使用 OpenCV 模板识别。`config/templates/` 保存微信主页、
搜索框、美团图标和美团搜索结果的局部 PNG 模板。模板匹配支持小幅比例变化，置信度至少为 0.82；
美团图标和搜索结果须在连续两帧中位置稳定才允许点击。模板缺失或置信度不足时，流程安全结束，
不会发送点击。

## 扩展点

- `adb_factory`：替换真实 ADB 实现或测试桩
- `model_factory`：按账号名称返回 `wechat_ctrip` / `wechat_meituan` 模型
- `BaseLayerModel.run_task`：实现领取、执行、查询的业务闭环

## 异常边界

- 设备离线：`DeviceManager` 不产出该设备
- 配置错误：`load_config` 立即抛出 `ConfigError`
- 页面异常：业务模型使用 `back_one` / `back_recover` 恢复
- 任务异常：`run_task` 返回 `False` 结束当前账号，避免阻塞其他设备线程
