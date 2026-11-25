package top.luotiany1.mcqq.crossplay;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** GAL v1 structured event payload. Collection and frame sizes are bounded before allocation. */
final class GalEventData {
    private static final int VERSION = 1;
    private static final int MAX_DEPTH = 12;
    private static final int MAX_ENTRIES = 256;
    private static final BigInteger UINT64_LIMIT = BigInteger.ONE.shiftLeft(64);

    private GalEventData() {}

    static byte[] encode(Map<String, Object> data) {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (DataOutputStream out = new DataOutputStream(bytes)) {
            out.writeByte(VERSION);
            writeMap(out, data, 0);
        } catch (IOException invalid) {
            throw new IllegalArgumentException("Invalid structured event data", invalid);
        }
        byte[] payload = bytes.toByteArray();
        GalPacket.requirePayload(payload);
        return payload;
    }

    static Map<String, Object> decode(byte[] bytes) {
        GalPacket.requirePayload(bytes);
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(bytes))) {
            if (in.readUnsignedByte() != VERSION) {
                throw new IllegalArgumentException("Unknown structured event payload version");
            }
            Map<String, Object> data = readMap(in, 0);
            if (in.read() != -1) {
                throw new IllegalArgumentException("Trailing structured event data");
            }
            return data;
        } catch (IOException invalid) {
            throw new IllegalArgumentException("Invalid structured event data", invalid);
        }
    }

    private static void writeMap(DataOutputStream out, Map<?, ?> map, int depth) throws IOException {
        checkCollection(map.size(), depth);
        out.writeShort(map.size());
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (!(entry.getKey() instanceof String)) {
                throw new IllegalArgumentException("Structured event keys must be strings");
            }
            writeString(out, (String) entry.getKey());
            writeValue(out, entry.getValue(), depth + 1);
        }
    }

    private static void writeValue(DataOutputStream out, Object data, int depth) throws IOException {
        if (data == null) {
            out.writeByte(0);
        } else if (data instanceof Boolean) {
            out.writeByte((Boolean) data ? 2 : 1);
        } else if (data instanceof Integer || data instanceof Short || data instanceof Byte) {
            out.writeByte(3);
            out.writeInt(((Number) data).intValue());
        } else if (data instanceof Long) {
            out.writeByte(4);
            out.writeLong((Long) data);
        } else if (data instanceof Double || data instanceof Float) {
            out.writeByte(5);
            out.writeDouble(((Number) data).doubleValue());
        } else if (data instanceof String) {
            out.writeByte(6);
            writeString(out, (String) data);
        } else if (data instanceof List<?>) {
            List<?> list = (List<?>) data;
            checkCollection(list.size(), depth);
            out.writeByte(7);
            out.writeShort(list.size());
            for (Object item : list) {
                writeValue(out, item, depth + 1);
            }
        } else if (data instanceof Map<?, ?>) {
            out.writeByte(8);
            writeMap(out, (Map<?, ?>) data, depth);
        } else if (data instanceof BigInteger) {
            BigInteger value = (BigInteger) data;
            if (value.signum() < 0 || value.compareTo(UINT64_LIMIT) >= 0) {
                throw new IllegalArgumentException("Structured event BigInteger must fit in unsigned 64 bits");
            }
            out.writeByte(9);
            out.writeLong(value.longValue());
        } else {
            throw new IllegalArgumentException("Unsupported structured event value");
        }
        checkWriteSize(out);
    }

    private static void writeString(DataOutputStream out, String value) throws IOException {
        if (value.length() > GalPacket.MAX_PAYLOAD) {
            throw new IllegalArgumentException("Structured event string is too long");
        }
        out.writeUTF(value);
        checkWriteSize(out);
    }

    private static void checkWriteSize(DataOutputStream out) {
        if (out.size() > GalPacket.MAX_PAYLOAD) {
            throw new IllegalArgumentException("Structured event exceeds 8192 bytes");
        }
    }

    private static Map<String, Object> readMap(DataInputStream in, int depth) throws IOException {
        int count = in.readUnsignedShort();
        checkCollection(count, depth);
        Map<String, Object> values = new LinkedHashMap<>();
        for (int i = 0; i < count; i++) {
            String key = in.readUTF();
            if (values.containsKey(key)) {
                throw new IllegalArgumentException("Duplicate structured event key");
            }
            values.put(key, readValue(in, depth + 1));
        }
        return values;
    }

    private static Object readValue(DataInputStream in, int depth) throws IOException {
        switch (in.readUnsignedByte()) {
            case 0: return null;
            case 1: return false;
            case 2: return true;
            case 3: return in.readInt();
            case 4: return in.readLong();
            case 5: return in.readDouble();
            case 6: return in.readUTF();
            case 7:
                int count = in.readUnsignedShort();
                checkCollection(count, depth);
                List<Object> items = new ArrayList<>(count);
                for (int i = 0; i < count; i++) {
                    items.add(readValue(in, depth + 1));
                }
                return items;
            case 8: return readMap(in, depth);
            case 9:
                BigInteger value = BigInteger.valueOf(in.readLong());
                return value.signum() >= 0 ? value : value.add(UINT64_LIMIT);
            default: throw new IllegalArgumentException("Unknown structured event value");
        }
    }

    private static void checkCollection(int count, int depth) {
        if (count > MAX_ENTRIES || depth > MAX_DEPTH) {
            throw new IllegalArgumentException("Structured event exceeds collection limits");
        }
    }
}
