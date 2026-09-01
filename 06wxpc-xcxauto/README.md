# Windows 微信小程序自动化

该模块通过 Windows 可见界面操作已正常登录的微信客户端，用于打开小程序并执行配置化步骤。它不实现微信私有协议、不读取 Cookie，也不处理 A16 或扫码登录。

## 安装

在 `06wxpc-xcxauto` 目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

首次使用 PaddleOCR 会下载所需模型。请先在 Windows 微信客户端中完成登录，并保持微信窗口可见。

## 配置与运行

编辑 `config.json` 中的小程序名称和 `actions`，然后运行：

```powershell
python main.py
```

支持的动作：

- `wait`：等待指定秒数。
- `wait_for_text`：OCR 等待指定文字出现。
- `click_text`：OCR 找到包含指定文字的区域并点击。
- `click_relative`：按微信窗口宽高的相对坐标点击，`x`、`y` 取值为 `0` 到 `1`。
- `click_template`：匹配 `templates/` 或其他相对路径中的 PNG 模板后点击。
- `screenshot`：将微信窗口截图保存到 `artifacts/screenshots/`。

页面结构会随微信版本、小程序更新、DPI 缩放和弹窗变化而变化。应为每一步添加文字、模板或截图校验，并在专用测试账号上先行验证。
