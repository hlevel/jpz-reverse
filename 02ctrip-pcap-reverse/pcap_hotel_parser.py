#!/usr/bin/env python3
"""Extract embedded JSON documents from Ctrip SOTP traffic in a PCAP."""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Iterable

try:
    import zstandard
except ImportError:  # zstd is only needed for handleType 4/5 payloads.
    zstandard = None


FOLLOW_HEX_LINE = re.compile(r"^(\t?)([0-9a-fA-F]+)$")
DEFAULT_PCAP = Path(__file__).resolve().parent / "work" / "PCAPdroid_06_8月_18_51_57.pcap"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "hotel_documents.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode Ctrip SOTP v2/v6 TCP streams from a PCAP and write JSON documents."
    )
    parser.add_argument("pcap", nargs="?", type=Path, default=DEFAULT_PCAP, help="input PCAP/PCAPNG file")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="output JSON file")
    parser.add_argument("--tshark", default=find_tshark(), help="path to tshark executable")
    args = parser.parse_args()

    documents = analyze(args.pcap, args.tshark)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(documents)} JSON document(s) to {args.output}")
    return 0


def analyze(pcap: Path, tshark: str | None) -> list[object]:
    require_file(pcap)

    documents: list[object] = []
    streams = follow_streams_with_tshark(pcap, tshark) if tshark else follow_streams_from_raw_pcap(pcap)
    for stream in streams:
        for direction in stream:
            if not looks_like_sotp(direction):
                continue
            try:
                payloads = decode_sotp_frames(direction)
            except ValueError:
                continue
            for payload in payloads:
                text = payload.decode("utf-8", errors="replace")
                documents.extend(extract_json_documents(text))
    return documents


def follow_streams_with_tshark(pcap: Path, tshark: str) -> list[tuple[bytes, bytes]]:
    return [follow_stream(pcap, tshark, stream) for stream in find_tcp_streams(pcap, tshark)]


def find_tcp_streams(pcap: Path, tshark: str) -> list[int]:
    output = run_tshark([tshark, "-r", str(pcap), "-Y", "tcp", "-T", "fields", "-e", "tcp.stream"])
    streams = set()
    for line in output.splitlines():
        line = line.strip()
        if line:
            streams.add(int(line))
    return sorted(streams)


def follow_stream(pcap: Path, tshark: str, stream: int) -> tuple[bytes, bytes]:
    output = run_tshark([tshark, "-r", str(pcap), "-q", "-z", f"follow,tcp,raw,{stream}"])
    client = bytearray()
    server = bytearray()
    for line in output.splitlines():
        match = FOLLOW_HEX_LINE.match(line)
        if not match:
            continue
        chunk = bytes.fromhex(match.group(2))
        if match.group(1):
            server.extend(chunk)
        else:
            client.extend(chunk)
    return bytes(client), bytes(server)


def follow_streams_from_raw_pcap(pcap: Path) -> list[tuple[bytes, bytes]]:
    packets = read_pcap_packets(pcap)
    streams: dict[tuple[tuple[str, int], tuple[str, int]], list[list[tuple[int, int, bytes]]]] = {}

    for order, packet in packets:
        parsed = parse_raw_ipv4_tcp(packet)
        if parsed is None:
            continue
        src_ip, src_port, dst_ip, dst_port, seq, payload = parsed
        if not payload:
            continue

        left = (src_ip, src_port)
        right = (dst_ip, dst_port)
        key = (left, right) if left <= right else (right, left)
        direction = 0 if key[0] == left else 1
        streams.setdefault(key, [[], []])[direction].append((seq, order, payload))

    return [
        (reassemble_tcp_payload(directions[0]), reassemble_tcp_payload(directions[1]))
        for _, directions in sorted(streams.items())
    ]


def read_pcap_packets(pcap: Path) -> list[tuple[int, bytes]]:
    data = pcap.read_bytes()
    if len(data) < 24:
        raise ValueError("invalid PCAP: file is too short")

    magic = data[:4]
    if magic == b"\xd4\xc3\xb2\xa1":
        endian = "<"
    elif magic == b"\xa1\xb2\xc3\xd4":
        endian = ">"
    elif magic == b"\x4d\x3c\xb2\xa1":
        endian = "<"
    elif magic == b"\xa1\xb2\x3c\x4d":
        endian = ">"
    else:
        raise ValueError("unsupported capture format: expected classic PCAP")

    link_type = struct.unpack_from(endian + "I", data, 20)[0]
    if link_type != 101:
        raise ValueError(f"pure Python parser only supports Raw IPv4 PCAP linktype 101, got {link_type}")

    offset = 24
    order = 0
    packets = []
    while offset + 16 <= len(data):
        _, _, captured_length, _ = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        packet = data[offset : offset + captured_length]
        if len(packet) != captured_length:
            break
        packets.append((order, packet))
        order += 1
        offset += captured_length
    return packets


def parse_raw_ipv4_tcp(packet: bytes) -> tuple[str, int, str, int, int, bytes] | None:
    if len(packet) < 40:
        return None
    version = packet[0] >> 4
    ihl = (packet[0] & 0x0F) * 4
    if version != 4 or ihl < 20 or len(packet) < ihl + 20:
        return None

    total_length = int.from_bytes(packet[2:4], "big")
    protocol = packet[9]
    flags_fragment = int.from_bytes(packet[6:8], "big")
    fragment_offset = flags_fragment & 0x1FFF
    if protocol != 6 or fragment_offset != 0:
        return None

    ip_packet = packet[: min(total_length, len(packet))]
    src_ip = ".".join(str(part) for part in ip_packet[12:16])
    dst_ip = ".".join(str(part) for part in ip_packet[16:20])
    tcp = ip_packet[ihl:]
    src_port = int.from_bytes(tcp[0:2], "big")
    dst_port = int.from_bytes(tcp[2:4], "big")
    seq = int.from_bytes(tcp[4:8], "big")
    tcp_header_length = (tcp[12] >> 4) * 4
    if tcp_header_length < 20 or len(tcp) < tcp_header_length:
        return None
    return src_ip, src_port, dst_ip, dst_port, seq, tcp[tcp_header_length:]


def reassemble_tcp_payload(segments: list[tuple[int, int, bytes]]) -> bytes:
    if not segments:
        return b""

    output = bytearray()
    next_seq: int | None = None
    for seq, _, payload in sorted(segments, key=lambda item: (item[0], item[1])):
        if next_seq is None:
            output.extend(payload)
            next_seq = seq + len(payload)
            continue
        overlap = next_seq - seq
        if overlap >= len(payload):
            continue
        if overlap > 0:
            payload = payload[overlap:]
        output.extend(payload)
        next_seq = seq + len(payload)
    return bytes(output)


def looks_like_sotp(stream: bytes) -> bool:
    if len(stream) < 14:
        return False
    try:
        length = ascii_int(stream, 0, 8)
        ascii_int(stream, 8, 4)
        ascii_int(stream, 12, 2)
    except ValueError:
        return False
    return length >= 6 and length + 8 <= len(stream)


def decode_sotp_frames(stream: bytes) -> list[bytes]:
    decoded = []
    offset = 0
    frame_index = 0
    while offset + 14 <= len(stream):
        length = ascii_int(stream, offset, 8)
        handle_type = ascii_int(stream, offset + 8, 4)
        total_length = 8 + length
        if length < 6 or offset + total_length > len(stream):
            raise ValueError(f"invalid SOTP frame length {length} @ {offset}")

        payload = bytearray(stream[offset + 14 : offset + total_length])
        try:
            decoded.append(decode_payload(handle_type, payload))
        except Exception as error:
            if not is_payload_decode_error(error):
                raise
            print(
                f"warning: skipped SOTP frame {frame_index} @ {offset}: "
                f"handleType={handle_type}, payload could not be decoded: {error}",
                file=sys.stderr,
            )
        offset += total_length
        frame_index += 1
    return decoded


def decode_payload(handle_type: int, payload: bytearray) -> bytes:
    if handle_type in (3, 5):
        payload = bytearray(byte ^ 0xFF for byte in payload)
    raw = bytes(payload)

    if handle_type in (1, 3):
        return gzip.decompress(raw)
    if handle_type in (4, 5):
        if zstandard is None:
            raise RuntimeError("zstandard is required for SOTP zstd payloads. Run: python -m pip install zstandard")
        return decompress_zstd(raw)
    if handle_type == 0:
        return raw
    raise ValueError(f"unsupported SOTP dataHandleType: {handle_type}")


def decompress_zstd(raw: bytes) -> bytes:
    decompressor = zstandard.ZstdDecompressor()
    with decompressor.stream_reader(io.BytesIO(raw)) as reader:
        return reader.read()


def is_payload_decode_error(error: Exception) -> bool:
    if isinstance(error, (EOFError, OSError, gzip.BadGzipFile)):
        return True
    return zstandard is not None and isinstance(error, zstandard.ZstdError)


def extract_json_documents(text: str) -> list[object]:
    documents = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        if text[index] not in "{[":
            index += 1
            continue
        try:
            document, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        documents.append(document)
        index += max(end, 1)
    return documents


def ascii_int(data: bytes, offset: int, length: int) -> int:
    field = data[offset : offset + length].decode("ascii").strip()
    return int(field)


def run_tshark(command: Iterable[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"tshark failed ({completed.returncode}): {completed.stderr.strip()}")
    return completed.stdout


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"PCAP file does not exist: {path}")


def find_tshark() -> str | None:
    found = shutil.which("tshark")
    if found:
        return found

    candidates = (
        Path(r"C:\Program Files\Wireshark\tshark.exe"),
        Path(r"C:\Program Files (x86)\Wireshark\tshark.exe"),
        Path(r"D:\Program Files\Wireshark\tshark.exe"),
        Path(r"D:\Program Files (x86)\Wireshark\tshark.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
