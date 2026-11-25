package top.luotiany1.mcqq.crossplay;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

public final class BedrockForm {
    static final String CHANNEL = "mcqq:galform";
    // Sent by Bungee on the current backend connection after Floodgate identification.
    static final byte[] AVAILABLE = {1, 2};
    static final int MAX_BYTES = 16_384;
    public static final int CLOSED = -1;
    public static final int UNAVAILABLE = -2;
    private static final int MAX_BUTTONS = 16;
    private static final int VERSION = 1;
    private static final int OPEN = 0;
    private static final int RESULT = 1;

    public final String title;
    public final String content;
    public final List<Button> buttons;

    public BedrockForm(String title, String content, List<Button> buttons) {
        this.title = bounded(title, 128);
        this.content = bounded(content, 2048);
        if (buttons.isEmpty() || buttons.size() > MAX_BUTTONS) {
            throw new IllegalArgumentException("A form needs 1 to 16 buttons");
        }
        this.buttons = Collections.unmodifiableList(new ArrayList<>(buttons));
        this.buttons.forEach(Objects::requireNonNull);
    }

    byte[] encodeOpen(int id) {
        return encode(OPEN, id, output -> {
            output.writeUTF(title);
            output.writeUTF(content);
            output.writeByte(buttons.size());
            for (Button button : buttons) {
                output.writeUTF(button.label);
                output.writeUTF(button.texture);
            }
        });
    }

    static byte[] encodeResult(int id, int index) {
        return encode(RESULT, id, output -> output.writeByte(index));
    }

    private static byte[] encode(int kind, int id, Body body) {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (DataOutputStream output = new DataOutputStream(bytes)) {
            output.writeByte(VERSION);
            output.writeByte(kind);
            output.writeInt(id);
            body.write(output);
        } catch (IOException unexpected) {
            throw new IllegalStateException(unexpected);
        }
        if (bytes.size() > MAX_BYTES) {
            throw new IllegalArgumentException("Bedrock form exceeds the wire size limit");
        }
        return bytes.toByteArray();
    }

    static Frame decode(byte[] bytes) {
        if (bytes.length > MAX_BYTES) {
            return null;
        }
        try (DataInputStream input = new DataInputStream(new ByteArrayInputStream(bytes))) {
            if (input.readUnsignedByte() != VERSION) {
                return null;
            }
            int kind = input.readUnsignedByte();
            int id = input.readInt();
            Frame frame;
            if (kind == RESULT) {
                int index = input.readByte();
                if (index < UNAVAILABLE || index >= MAX_BUTTONS) {
                    return null;
                }
                frame = new Frame(id, null, index);
            } else if (kind == OPEN) {
                String title = input.readUTF();
                String content = input.readUTF();
                int count = input.readUnsignedByte();
                if (count < 1 || count > MAX_BUTTONS) {
                    return null;
                }
                List<Button> buttons = new ArrayList<>(count);
                for (int i = 0; i < count; i++) {
                    buttons.add(new Button(input.readUTF(), input.readUTF()));
                }
                frame = new Frame(id, new BedrockForm(title, content, buttons), UNAVAILABLE);
            } else {
                return null;
            }
            return input.read() == -1 ? frame : null;
        } catch (IOException | IllegalArgumentException invalid) {
            return null;
        }
    }

    private static String bounded(String value, int limit) {
        if (Objects.requireNonNull(value).length() > limit) {
            throw new IllegalArgumentException("Form text is too long");
        }
        return value;
    }

    public static final class Button {
        public final String label;
        public final String texture;

        public Button(String label) {
            this(label, "");
        }

        public Button(String label, String texture) {
            this.label = bounded(label, 128);
            this.texture = bounded(texture, 149);
            if (!texture.isEmpty() && !texture.matches("textures/(?:[a-z0-9_-]+/)*[a-z0-9_-]+(?:\\.png)?")) {
                throw new IllegalArgumentException("Use a Bedrock resource-pack texture path");
            }
        }
    }

    static final class Frame {
        final int id;
        final BedrockForm form;
        final int index;

        Frame(int id, BedrockForm form, int index) {
            this.id = id;
            this.form = form;
            this.index = index;
        }
    }

    private interface Body {
        void write(DataOutputStream output) throws IOException;
    }
}
