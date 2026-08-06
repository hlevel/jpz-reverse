# 03ctrip-ldauto

基于 Python + venv 的雷电模拟器自动化工程。当前阶段先以设计文档驱动实现，`work/` 目录只作为临时参考资料和实验内容，不作为正式工程代码入口。

## 文档入口

- [系统设计文档](docs/design.md)

## 约定

- 正式代码后续放在 `src/ctrip_ldauto/`。
- 配置文件后续放在 `configs/`。
- 运行数据、cookie、任务、pcap、日志统一放在 `data/`。
- `work/ldscript-automation` 仅参考其中雷电核心能力：`ldconsole.exe` 封装、ADB、应用包检测、点击、返回、输入、截图。
