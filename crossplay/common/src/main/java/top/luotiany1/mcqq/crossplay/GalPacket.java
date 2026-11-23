package top.luotiany1.mcqq.crossplay;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.regex.Pattern;

public final class GalPacket {
    public static final String CLIENT_CHANNEL = "mcqq:gal";
    public static final String BACKEND_CHANNEL = "mcqq:galbus";
    public static final int MAX_PAYLOAD = 8192;
    public static final int MAX_FRAME = MAX_PAYLOAD + 87;

    private static final int VERSION = 1;
    private static final int HEADER = 7;
    private static final Pattern ACTION = Pattern.compile("[a-z0-9_.-]+:[a-z0-9_./-]+");
    private static final byte[] EMPTY = new byte[0];

    public enum Kind {
        HELLO(0), WELCOME(1), RESET(2), EVENT(3), REQUEST(4), RESPONSE(5), ERROR(6);

        private final int code;

        Kind(int code) {
            this.code = code;
        }
    }

    private static final Kind[] KINDS = Kind.values();
    public final Kind kind;
    final int id;
    final String action;
    final byte[] payload;

    GalPacket(Kind kind, int id, String action, byte[] payload) {
        this.kind = kind;
        this.id = id;
        this.action = action;
        this.payload = payload;
    }

    public static byte[] reset() {
        return new GalPacket(Kind.RESET, 0, "", EMPTY).encode();
    }

    static boolean validAction(String action) {
        return action != null && action.length() <= 80 && ACTION.matcher(action).matches();
    }

    static void requirePayload(byte[] payload) {
        if (payload == null || payload.length > MAX_PAYLOAD) {
            throw new IllegalArgumentException("MasterGAL payload must contain at most 8192 bytes");
        }
    }

    byte[] encode() {
        requirePayload(payload);
        byte[] name = action.getBytes(StandardCharsets.US_ASCII);
        return ByteBuffer.allocate(HEADER + name.length + payload.length)
                .put((byte) VERSION).put((byte) kind.code).putInt(id).put((byte) name.length)
                .put(name).put(payload).array();
    }

    public static GalPacket decode(byte[] frame) {
        if (frame.length < HEADER || frame.length > MAX_FRAME) {
            return null;
        }
        ByteBuffer buffer = ByteBuffer.wrap(frame);
        if (Byte.toUnsignedInt(buffer.get()) != VERSION) {
            return null;
        }
        int opcode = Byte.toUnsignedInt(buffer.get());
        if (opcode >= KINDS.length) {
            return null;
        }
        Kind kind = KINDS[opcode];
        int id = buffer.getInt();
        int nameLength = Byte.toUnsignedInt(buffer.get());
        if (nameLength > 80 || nameLength > buffer.remaining()
                || buffer.remaining() - nameLength > MAX_PAYLOAD) {
            return null;
        }
        byte[] name = new byte[nameLength];
        buffer.get(name);
        String action = new String(name, StandardCharsets.US_ASCII);
        byte[] payload = new byte[buffer.remaining()];
        buffer.get(payload);
        switch (kind) {
            case HELLO:
            case WELCOME:
                return nameLength == 0 && id == 0 ? new GalPacket(kind, id, action, payload) : null;
            case RESET:
                return nameLength == 0 && id == 0 && payload.length == 0
                        ? new GalPacket(kind, id, action, payload) : null;
            case EVENT:
                return id == 0 && validAction(action) ? new GalPacket(kind, id, action, payload) : null;
            case ERROR:
                if (payload.length != 0) {
                    return null;
                }
                // Fall through to the request ID and action checks.
            case REQUEST:
            case RESPONSE:
                return id != 0 && validAction(action) ? new GalPacket(kind, id, action, payload) : null;
            default:
                return null;
        }
    }
}
