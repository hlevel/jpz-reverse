package com.jpz.collector.util;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.github.luben.zstd.ZstdInputStream;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.GZIPInputStream;

/** Decrypts Ctrip SOTP v2/v6 traffic in a PCAP and prints the embedded JSON documents. */
public final class PcapHotelParser {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Pattern FOLLOW_HEX_LINE = Pattern.compile("^(\\t?)([0-9a-fA-F]+)$");

    private PcapHotelParser() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 1 || args.length > 2) {
            System.err.println("用法: PcapHotelParser <capture.pcap> [tshark路径]");
            //System.exit(2);
        }
        //Path pcap = Path.of(args[0]);
        Path pcap = Path.of("D:\\workspace\\idea\\github\\jpz-collector\\data\\debug\\PCAPdroid_28_7月_09_25_01_3个酒店.pcap");
        String tshark = args.length == 2 ? args[1] : "D:\\Program Files\\Wireshark\\tshark.exe";
        System.out.println(JSON.writerWithDefaultPrettyPrinter().writeValueAsString(analyze(pcap, tshark)));
    }

    static ArrayNode analyze(Path pcap, String tshark) throws Exception {
        requireFile(pcap);
        ArrayNode documents = JSON.createArrayNode();
        for (int stream : findTcpStreams(pcap, tshark)) {
            for (byte[] direction : followStream(pcap, tshark, stream)) {
                if (!looksLikeSotp(direction)) continue;
                for (byte[] payload : decodeSotpFrames(direction)) {
                    documents.addAll(extractJsonDocuments(new String(payload, StandardCharsets.UTF_8)));
                }
            }
        }
        return documents;
    }

    private static Set<Integer> findTcpStreams(Path pcap, String tshark) throws Exception {
        String output = runTshark(List.of(tshark, "-r", pcap.toString(), "-Y", "tcp",
                "-T", "fields", "-e", "tcp.stream"));
        Set<Integer> streams = new TreeSet<>();
        for (String line : output.split("\\R")) {
            if (!line.isBlank()) streams.add(Integer.parseInt(line.strip()));
        }
        return streams;
    }

    private static List<byte[]> followStream(Path pcap, String tshark, int stream) throws Exception {
        String output = runTshark(List.of(tshark, "-r", pcap.toString(), "-q", "-z", "follow,tcp,raw," + stream));
        ByteArrayOutputStream client = new ByteArrayOutputStream();
        ByteArrayOutputStream server = new ByteArrayOutputStream();
        for (String line : output.split("\\R")) {
            Matcher matcher = FOLLOW_HEX_LINE.matcher(line);
            if (!matcher.matches()) continue;
            (matcher.group(1).isEmpty() ? client : server).writeBytes(decodeHex(matcher.group(2)));
        }
        return List.of(client.toByteArray(), server.toByteArray());
    }

    private static boolean looksLikeSotp(byte[] stream) {
        if (stream.length < 14) return false;
        try {
            int length = asciiInt(stream, 0, 8);
            asciiInt(stream, 8, 4);
            asciiInt(stream, 12, 2);
            return length >= 6 && length + 8 <= stream.length;
        } catch (IOException ignored) {
            return false;
        }
    }

    static List<byte[]> decodeSotpFrames(byte[] stream) throws IOException {
        List<byte[]> decoded = new ArrayList<>();
        int offset = 0;
        while (offset + 14 <= stream.length) {
            int length = asciiInt(stream, offset, 8);
            int handleType = asciiInt(stream, offset + 8, 4);
            int totalLength = 8 + length;
            if (length < 6 || offset + totalLength > stream.length) {
                throw new IOException("无效的 SOTP 帧长度: " + length + " @ " + offset);
            }
            byte[] payload = java.util.Arrays.copyOfRange(stream, offset + 14, offset + totalLength);
            decoded.add(decodePayload(handleType, payload));
            offset += totalLength;
        }
        return decoded;
    }

    private static byte[] decodePayload(int handleType, byte[] payload) throws IOException {
        if (handleType == 3 || handleType == 5) {
            for (int i = 0; i < payload.length; i++) payload[i] ^= (byte) 0xFF;
        }
        if (handleType == 1 || handleType == 3) {
            try (GZIPInputStream input = new GZIPInputStream(new ByteArrayInputStream(payload))) {
                return input.readAllBytes();
            }
        }
        if (handleType == 4 || handleType == 5) {
            try (ZstdInputStream input = new ZstdInputStream(new ByteArrayInputStream(payload))) {
                return input.readAllBytes();
            }
        }
        if (handleType == 0) return payload;
        throw new IOException("不支持的 SOTP dataHandleType: " + handleType);
    }

    static List<JsonNode> extractJsonDocuments(String text) {
        List<JsonNode> documents = new ArrayList<>();
        for (int start = 0; start < text.length(); start++) {
            char first = text.charAt(start);
            if (first != '{' && first != '[') continue;
            try (JsonParser parser = JSON.createParser(text.substring(start))) {
                JsonNode document = JSON.readTree(parser);
                if (document == null) continue;
                documents.add(document);
                long consumed = parser.currentLocation().getCharOffset();
                if (consumed > 0) start += (int) consumed - 1;
            } catch (IOException ignored) {
                // A binary protocol prefix may contain brace bytes that are not JSON starts.
            }
        }
        return documents;
    }

    private static int asciiInt(byte[] bytes, int offset, int length) throws IOException {
        try {
            return Integer.parseInt(new String(bytes, offset, length, StandardCharsets.US_ASCII).strip());
        } catch (NumberFormatException exception) {
            throw new IOException("无效的 SOTP ASCII 数字字段 @ " + offset, exception);
        }
    }

    private static byte[] decodeHex(String hex) {
        byte[] bytes = new byte[hex.length() / 2];
        for (int i = 0; i < bytes.length; i++) bytes[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        return bytes;
    }

    private static String runTshark(List<String> command) throws Exception {
        Process process = new ProcessBuilder(command).start();
        String stdout = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        String stderr = new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8);
        int exit = process.waitFor();
        if (exit != 0) throw new IOException("tshark 执行失败(" + exit + "): " + stderr.strip());
        return stdout;
    }

    private static void requireFile(Path path) {
        if (!Files.isRegularFile(path)) throw new IllegalArgumentException("PCAP 文件不存在: " + path);
    }
}
