# 携程页面指纹脚本与 VirtualBrowser 配置一致性复核

> 结论：文章描述的 config-level 指纹风险，在本地携程页面脚本中存在对应检测面；25 份 VirtualBrowser 配置还出现了可直接验证的跨 API 矛盾。现有证据能证明“可被识别和聚类”，不能证明服务端最终仅凭 Canvas 批量封号。

## 证据范围

- E-006：用户提供的文章《CloakBrowser源码级反爬虫：57个C++指纹补丁深度解析》。其核心检查面为 Canvas、WebGL、WebRTC、Audio、字体、时序、自动化变量、函数改写痕迹和跨 API 一致性。
- E-007：两份本地 HTML 均引用 `d.min.aa836653.js`、`c-sec.js`、`c-sign.js`、`foundation.js` 和 `index.js`，因此不是“目录里碰巧存在但页面未加载”。
- E-008：`Virtual-Browser_0821_全量封号.json`，实际包含 25 个配置。
- E-009：可复现分析脚本 `../analyze_profiles.js` 与 `../extract_evidence.js`。

## 文章检查面与携程代码对应关系

| 检查面 | 本地代码证据 | 状态 |
|---|---|---|
| Canvas | `d.min` 构造 `canvasFp` 并取得 Canvas 数据；`c-sec` 有 `canvasFp` 生成逻辑 | 已证实；`d.min` 进入设备画像上报对象 |
| WebGL | `d.min` 收集 WebGL1/2、unmasked vendor/renderer、扩展、精度和 WebGL 图像 | 已证实；进入设备画像上报对象 |
| WebRTC | `d.min` 创建 `RTCPeerConnection`、解析 ICE candidate，写入 `webRtc` | 已证实；进入设备画像上报对象 |
| 字体 | `d.min` 枚举系统字体并写入 `sysfonts` | 已证实；进入设备画像上报对象 |
| 自动化 | `d.min` 读取 `navigator.webdriver`；`foundation` 检查 Playwright/WebDriver | 已证实；`foundation` 的 Bot 评分受 `openCheckBot` 配置控制 |
| 注入/改写痕迹 | `c-sign`、`c-sec` 对 Canvas/WebGL/Audio 等原生函数做完整性检查；`c-sec` 还查 AdsPower/花漾扩展 DOM/CSS 痕迹 | 已证实代码与页面加载；具体命中结果需运行时采样 |
| Audio | `index.js` 创建 `OfflineAudioContext`；`c-sign/c-sec` 检查 Audio API 原生性 | 已证实采集/检查代码；静态样本未完整证明该结果进入哪个最终请求字段 |
| Storage quota | `index.js` 调用 `navigator.storage.estimate()` | 已证实采集代码；静态样本未完整证明最终上报端点 |
| WebGPU | `index.js` 调用 `navigator.gpu.requestAdapter()` / `requestDevice()` | 已证实采集代码；静态样本未完整证明最终上报端点 |
| 持久设备标识 | `d.min` POST 到 `cdid.c-ctrip.com/chloro-device/v2/d`，并处理 `_RGUID/_RSG/_RDG` | 已证实采集—提交—持久化闭环 |

`c-sec` 中高级 Canvas/WebGL/WebRTC 分支还受 `window.fp_canvas`、`window.fp_webgl`、`window.fp_webrtc` 等开关控制，不能把这些分支一律写成无条件执行。但 `d.min` 已独立完成 Canvas/WebGL/WebRTC/字体等核心采集和设备服务提交，因此核心结论不依赖这些开关。

## VirtualBrowser 配置中已验证的问题

### F-007：浏览器版本跨接口冲突

- status: validated
- evidence_ids: [E-008, E-009]
- confidence: high

25 个配置中有 2 个配置的 `chrome_version` 与 `sec-ch-ua` 冲突：一个声明 Chrome 145、另一个声明 Chrome 141，但两者的 Chromium brand version 都是 146。UA、UA Full Version、UA-CH 是同一浏览器版本的不同观测面，这种冲突不需要账号浏览很多次，一次页面加载即可读出。

### F-008：WebGL 型号与 WebGPU 架构存在多处代际冲突

- status: validated
- evidence_ids: [E-008, E-009]
- confidence: high

配置不是只随机 Canvas，而是分别随机 WebGL 与 WebGPU。多组组合在硬件代际上不可能或明显不合理，例如：

- GeForce GTX 750 Ti（Maxwell）配 `webgpu.architecture=turing`；
- GeForce GTX 980（Maxwell）配 `kepler`；
- GeForce GTX 1050 Ti（Pascal）配 `kepler`；
- GeForce GTX 1650（Turing）配 `maxwell`；
- Intel UHD 620（Gen9.5）配 `gen-12lp`；
- Intel HD 4600（Gen7.5）配 `gen-11`。

这正是文章所说的 config-level 问题：每个字段单看都“像真的”，组合后却不属于任何真实机器。页面中的 `index.js` 已具备读取 WebGPU 的代码，`d.min/foundation` 已读取和评估 WebGL；静态文件无法证明服务端采用了哪条交叉规则，但检测所需数据面客观存在。

### F-009：随机值唯一不等于真实或不可聚类

- status: validated
- evidence_ids: [E-008]
- confidence: high

25 个配置的 Canvas、WebGL image、AudioContext、ClientRects 和字体配置都是 25 个唯一值。这可以排除“25 个账号因完全相同 Canvas 值被直接合并”这一简单假设，却不能排除统一的修改算法、固定模式或跨 API 矛盾被识别。配置文件只给出噪声参数，不包含网页实际读到的 Canvas hash、函数描述符和 `Function.prototype.toString` 结果，因此目前不能断言 VirtualBrowser 是 C++ 原生修改还是 JS Hook，也不能断言具体哪一项完整性检查已命中。

## Evidence → Finding → Path

### P-002

1. 页面加载五个安全/指纹脚本（E-007）。
2. `d.min` 读取 Canvas、WebGL、WebRTC、字体、webdriver、屏幕和性能数据，构造设备画像（E-007）。
3. 画像提交至 Chloro 设备端点并形成持久设备标识（E-007）。
4. 同页其他脚本检查自动化变量、原生函数完整性、WebGPU、Audio 和存储配额（E-007）。
5. VirtualBrowser 配置在 UA/UA-CH、WebGL/WebGPU 之间出现可验证矛盾（E-008、E-009）。
6. 因而一次酒店页面访问已经足以暴露这些静态矛盾；浏览次数不是读取这些字段的必要条件。

## 可以下的结论与不能下的结论

可以确认：携程页面确实实现了文章所说的大部分指纹和自动化检测面，并存在设备画像上报闭环；现有 25 个配置至少有版本和 GPU 跨接口一致性问题。

不能确认：服务端最终是否专门使用 Canvas、WebGPU 或某个确定特征作为封号主因；也不能仅凭前端代码证明 60 个账号的最终关联规则。要把“具备能力”提升为“实际命中”，需要一次合规的运行时采样，记录页面真实返回的各 API 值、函数描述符以及 `/chloro-device/v2/d` 请求字段。

## 复现

```powershell
node work/ctrip-js-fingerprint-20260821/analyze_profiles.js
node work/ctrip-js-fingerprint-20260821/extract_evidence.js
```
