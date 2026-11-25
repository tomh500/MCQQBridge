package top.luotiany1.mcqq.crossplay;

import java.util.Map;
import java.util.Objects;
import java.util.function.BiConsumer;
import java.util.regex.Pattern;

/** Structured, directional events over the existing GAL capability exchange. */
public final class GalEventApi<Peer> {
    private static final Pattern NAME = Pattern.compile("[A-Za-z0-9_.-]+");
    private final GalApi<Peer> api;

    public GalEventApi(GalApi<Peer> api) {
        this.api = Objects.requireNonNull(api);
    }

    public void listenForEvent(String namespace, String system, String event,
                               BiConsumer<Peer, Map<String, Object>> handler) {
        Objects.requireNonNull(handler);
        api.onEvent(action(namespace, system, event), (peer, payload) ->
                handler.accept(peer, GalEventData.decode(payload)));
    }

    public boolean notifyPeer(Peer peer, String namespace, String system, String event,
                              Map<String, Object> data) {
        String action = action(namespace, system, event);
        return api.canSendEvent(peer, action) && api.sendEvent(peer, action, GalEventData.encode(data));
    }

    private static String action(String namespace, String system, String event) {
        String action = "galevent:" + segment(namespace) + "/" + segment(system) + "/" + segment(event);
        if (!GalPacket.validAction(action)) {
            throw new IllegalArgumentException("Structured event action exceeds 80 characters after escaping");
        }
        return action;
    }

    private static String segment(String name) {
        if (name == null || name.length() > 80 || !NAME.matcher(name).matches()) {
            throw new IllegalArgumentException("Invalid structured event name");
        }
        StringBuilder encoded = new StringBuilder();
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            if (c == '-') {
                encoded.append("--");
            } else if (c >= 'A' && c <= 'Z') {
                encoded.append('-').append(Character.toLowerCase(c));
            } else {
                encoded.append(c);
            }
        }
        return encoded.toString();
    }
}
