# Ctrip PCAP Reverse

本目录用于根据 Java 版 `PcapHotelParser.java` 复刻 Python 离线解析脚本，从携程酒店业务抓包中提取 SOTP v2/v6 payload 里的 JSON 文档。

## 文件说明

- `PcapHotelParser.java`: 原始 Java 解析逻辑。
- `pcap_hotel_parser.py`: Python 复刻版解析器。
- `requirements.txt`: Python 依赖，目前需要 `zstandard`。
- `work/`: 放置待解析的 pcap 和输出 json。

## 解析逻辑

脚本会枚举 TCP stream，并对每个方向做 SOTP 帧解析：

1. 读取 8 字节 ASCII 长度、4 字节 `dataHandleType`、2 字节保留字段。
2. `dataHandleType` 为 `3` 或 `5` 时，对 payload 执行 `0xFF` XOR。
3. `dataHandleType` 为 `1` 或 `3` 时，按 GZIP 解压。
4. `dataHandleType` 为 `4` 或 `5` 时，按 Zstd 流式解压。
5. 从解码后的 UTF-8 文本中扫描 JSON 对象或数组，并写入输出文件。

如果本机存在 `tshark`，脚本优先复用 Wireshark 的 `follow,tcp,raw` 输出；否则会尝试使用内置 Raw IPv4 PCAP 解析 fallback。

## 安装依赖

```powershell
python -m pip install -r 02ctrip-pcap-reverse\requirements.txt
```

## 运行命令

解析指定 pcap 并输出 json：

```powershell
python 02ctrip-pcap-reverse\pcap_hotel_parser.py 02ctrip-pcap-reverse\work\ctrip_hotel_20260806_211621.pcap -o 02ctrip-pcap-reverse\work\ctrip_hotel_20260806_211621.json
```

不传参数时，脚本会尝试解析目录内默认样本并输出到 `hotel_documents.json`：

```powershell
python 02ctrip-pcap-reverse\pcap_hotel_parser.py
```

## Warning 说明

某些抓包中可能出现 `payload could not be decoded` warning。这表示单个 SOTP 候选帧的 payload 与声明的压缩类型不匹配，或该帧残缺/非业务帧。脚本会跳过该帧，继续输出其他已成功解码的 JSON 文档。
