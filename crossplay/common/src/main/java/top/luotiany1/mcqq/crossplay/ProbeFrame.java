package top.luotiany1.mcqq.crossplay;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;

/** Wire format shared by the proxy, Bukkit plugin and Fabric client. */
public final class ProbeFrame {
    public static final String CLIENT_CHANNEL = "mcqq:crossplay";
    public static final String BACKEND_CHANNEL = "mcqq:crossbus";
    private static final byte VERSION = 1;
    private static final int HEADER_BYTES = 6;
    public static final int MAX_BYTES = 262;

    public enum Kind {
        REQUEST(0), SUCCESS(1), UNAVAILABLE(2);

        private final int opcode;

        Kind(int opcode) {
            this.opcode = opcode;
        }
    }

    public final Kind kind;
    public final int id;
    public final String world;

    private ProbeFrame(Kind kind, int id, String world) {
        this.kind = kind;
        this.id = id;
        this.world = world;
    }

    public static byte[] request(int id) {
        return encode(Kind.REQUEST, id, "");
    }

    public static byte[] success(int id, String world) {
        return encode(Kind.SUCCESS, id, world);
    }

    public static byte[] unavailable(int id) {
        return encode(Kind.UNAVAILABLE, id, "");
    }

    private static byte[] encode(Kind kind, int id, String world) {
        byte[] body = world.getBytes(StandardCharsets.UTF_8);
        if (kind == Kind.SUCCESS && (body.length == 0 || body.length > MAX_BYTES - HEADER_BYTES)) {
            return unavailable(id);
        }
        return ByteBuffer.allocate(HEADER_BYTES + body.length)
                .put(VERSION).put((byte) kind.opcode).putInt(id).put(body).array();
    }

    public static ProbeFrame decode(byte[] bytes) {
        if (bytes.length < HEADER_BYTES || bytes.length > MAX_BYTES) {
            return null;
        }
        ByteBuffer buffer = ByteBuffer.wrap(bytes);
        if (buffer.get() != VERSION) {
            return null;
        }
        Kind kind;
        switch (buffer.get()) {
            case 0: kind = Kind.REQUEST; break;
            case 1: kind = Kind.SUCCESS; break;
            case 2: kind = Kind.UNAVAILABLE; break;
            default: return null;
        }
        int id = buffer.getInt();
        if (kind == Kind.SUCCESS && !buffer.hasRemaining()) {
            return null;
        }
        if (kind != Kind.SUCCESS) {
            return buffer.hasRemaining() ? null : new ProbeFrame(kind, id, "");
        }
        try {
            String world = StandardCharsets.UTF_8.newDecoder().decode(buffer).toString();
            return new ProbeFrame(kind, id, world);
        } catch (CharacterCodingException invalidUtf8) {
            return null;
        }
    }
}
