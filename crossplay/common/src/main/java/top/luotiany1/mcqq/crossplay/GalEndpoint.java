package top.luotiany1.mcqq.crossplay;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.BiConsumer;
import java.util.function.BiFunction;
import java.util.function.Consumer;

final class GalEndpoint<P> implements GalApi<P> {
    private static final int EVENT = 1;
    private static final int REQUEST = 2;
    private static final int MAX_ACTIONS = 64;
    private static final int MAX_PENDING = 32;
    private static final long TIMEOUT = TimeUnit.SECONDS.toNanos(5);
    private static final byte[] EMPTY = new byte[0];

    private final boolean client;
    private final BiConsumer<P, byte[]> transport;
    private final Consumer<RuntimeException> onHandlerError;
    private final Map<String, BiConsumer<P, byte[]>> events = new HashMap<>();
    private final Map<String, BiFunction<P, byte[], byte[]>> requests = new HashMap<>();
    private final Map<String, Integer> local = new HashMap<>();
    private final Map<P, Session> peers = new HashMap<>();
    private final Set<P> negotiating = new HashSet<>();
    private final List<Consumer<P>> ready = new ArrayList<>();
    private int nextId;

    GalEndpoint(boolean client, BiConsumer<P, byte[]> transport, Consumer<RuntimeException> onHandlerError) {
        this.client = client;
        this.transport = transport;
        this.onHandlerError = onHandlerError;
    }

    @Override
    public void onEvent(String action, BiConsumer<P, byte[]> handler) {
        Objects.requireNonNull(handler);
        register(action, EVENT);
        events.put(action, handler);
    }

    @Override
    public void onRequest(String action, BiFunction<P, byte[], byte[]> handler) {
        Objects.requireNonNull(handler);
        register(action, REQUEST);
        requests.put(action, handler);
    }

    private void register(String action, int kind) {
        if (!GalPacket.validAction(action)) {
            throw new IllegalArgumentException("Use a namespaced MasterGAL action");
        }
        int existing = local.getOrDefault(action, 0);
        if ((existing & kind) != 0) {
            throw new IllegalArgumentException("Action already registered: " + action);
        }
        if (existing == 0 && local.size() >= MAX_ACTIONS) {
            throw new IllegalStateException("MasterGAL action registry is full");
        }
        local.put(action, existing | kind);
    }

    @Override
    public void onReady(Consumer<P> handler) {
        ready.add(Objects.requireNonNull(handler));
    }

    boolean isReady(P peer) {
        return peers.containsKey(peer);
    }

    private boolean supports(P peer, String action, int capability) {
        Session session = peers.get(peer);
        return session != null && (session.capabilities.getOrDefault(action, 0) & capability) != 0;
    }

    @Override
    public boolean canSendEvent(P peer, String action) {
        return supports(peer, action, EVENT);
    }

    @Override
    public boolean canRequest(P peer, String action) {
        return supports(peer, action, REQUEST);
    }

    @Override
    public boolean sendEvent(P peer, String action, byte[] payload) {
        if (!canSendEvent(peer, action)) {
            return false;
        }
        send(peer, GalPacket.Kind.EVENT, 0, action, payload);
        return true;
    }

    @Override
    public CompletableFuture<byte[]> request(P peer, String action, byte[] payload) {
        CompletableFuture<byte[]> result = new CompletableFuture<>();
        if (!canRequest(peer, action)) {
            result.completeExceptionally(new IllegalStateException("Peer does not advertise " + action));
            return result;
        }
        Session session = peers.get(peer);
        if (session.pending.size() >= MAX_PENDING) {
            result.completeExceptionally(new IllegalStateException("Too many pending MasterGAL requests"));
            return result;
        }
        GalPacket.requirePayload(payload);
        int id = ++nextId;
        if (id == 0) {
            id = ++nextId;
        }
        session.pending.put(id, new Pending(action, result));
        try {
            send(peer, GalPacket.Kind.REQUEST, id, action, payload);
        } catch (RuntimeException failure) {
            session.pending.remove(id);
            result.completeExceptionally(failure);
        }
        return result;
    }

    void begin(P peer) {
        negotiating.add(peer);
        send(peer, GalPacket.Kind.HELLO, 0, "", encodeCapabilities());
    }

    void receive(P peer, byte[] bytes) {
        GalPacket packet = GalPacket.decode(bytes);
        if (packet == null) {
            return;
        }
        if (packet.kind == GalPacket.Kind.RESET && client) {
            close(peer);
            return;
        }
        if (packet.kind == (client ? GalPacket.Kind.WELCOME : GalPacket.Kind.HELLO)) {
            negotiate(peer, packet.payload);
            return;
        }
        Session session = peers.get(peer);
        if (session == null) {
            return;
        }
        switch (packet.kind) {
            case EVENT:
                BiConsumer<P, byte[]> handler = events.get(packet.action);
                if (handler != null) {
                    safely(() -> handler.accept(peer, packet.payload));
                }
                break;
            case REQUEST:
                answer(peer, packet);
                break;
            case RESPONSE:
            case ERROR:
                Pending pending = session.pending.get(packet.id);
                if (pending != null && pending.action.equals(packet.action)) {
                    session.pending.remove(packet.id);
                    if (packet.kind == GalPacket.Kind.RESPONSE) {
                        pending.result.complete(packet.payload);
                    } else {
                        pending.result.completeExceptionally(new IllegalStateException("Peer rejected " + packet.action));
                    }
                }
                break;
            default:
                break;
        }
    }

    private void negotiate(P peer, byte[] payload) {
        Map<String, Integer> capabilities = decodeCapabilities(payload);
        if (capabilities == null || (client && !negotiating.remove(peer))) {
            return;
        }
        Session previous = peers.putIfAbsent(peer, new Session(capabilities));
        if (previous != null) {
            previous.capabilities = capabilities;
        }
        if (!client) {
            send(peer, GalPacket.Kind.WELCOME, 0, "", encodeCapabilities());
        }
        if (previous == null) {
            new ArrayList<>(ready).forEach(handler -> safely(() -> handler.accept(peer)));
        }
    }

    private void answer(P peer, GalPacket request) {
        BiFunction<P, byte[], byte[]> handler = requests.get(request.action);
        byte[] response;
        try {
            response = handler == null ? null : handler.apply(peer, request.payload);
            if (response != null) {
                GalPacket.requirePayload(response);
            }
        } catch (RuntimeException failure) {
            onHandlerError.accept(failure);
            response = null;
        }
        if (response == null) {
            send(peer, GalPacket.Kind.ERROR, request.id, request.action, EMPTY);
        } else {
            send(peer, GalPacket.Kind.RESPONSE, request.id, request.action, response);
        }
    }

    private void safely(Runnable task) {
        try {
            task.run();
        } catch (RuntimeException failure) {
            onHandlerError.accept(failure);
        }
    }

    void close(P peer) {
        negotiating.remove(peer);
        Session session = peers.remove(peer);
        if (session != null) {
            session.pending.values().forEach(request -> request.result.completeExceptionally(
                    new IllegalStateException("MasterGAL session changed")));
        }
    }

    void expire() {
        long now = System.nanoTime();
        List<Pending> timedOut = new ArrayList<>();
        for (Session session : peers.values()) {
            Iterator<Pending> requests = session.pending.values().iterator();
            while (requests.hasNext()) {
                Pending pending = requests.next();
                if (pending.result.isCancelled() || now - pending.sentAt >= TIMEOUT) {
                    requests.remove();
                    timedOut.add(pending);
                }
            }
        }
        timedOut.forEach(pending -> pending.result.completeExceptionally(
                new IllegalStateException("MasterGAL request timed out")));
    }

    private void send(P peer, GalPacket.Kind kind, int id, String action, byte[] payload) {
        transport.accept(peer, new GalPacket(kind, id, action, payload).encode());
    }

    private byte[] encodeCapabilities() {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        output.write(local.size());
        local.forEach((action, flags) -> {
            byte[] name = action.getBytes(StandardCharsets.US_ASCII);
            output.write(flags);
            output.write(name.length);
            output.write(name, 0, name.length);
        });
        return output.toByteArray();
    }

    private Map<String, Integer> decodeCapabilities(byte[] payload) {
        if (payload.length == 0) {
            return null;
        }
        ByteBuffer buffer = ByteBuffer.wrap(payload);
        int count = Byte.toUnsignedInt(buffer.get());
        if (count > MAX_ACTIONS) {
            return null;
        }
        Map<String, Integer> capabilities = new HashMap<>();
        for (int i = 0; i < count; i++) {
            if (buffer.remaining() < 2) {
                return null;
            }
            int flags = Byte.toUnsignedInt(buffer.get());
            int length = Byte.toUnsignedInt(buffer.get());
            if (flags < EVENT || flags > (EVENT | REQUEST) || length > 80 || length > buffer.remaining()) {
                return null;
            }
            byte[] bytes = new byte[length];
            buffer.get(bytes);
            String name = new String(bytes, StandardCharsets.US_ASCII);
            if (!GalPacket.validAction(name) || capabilities.putIfAbsent(name, flags) != null) {
                return null;
            }
        }
        return buffer.hasRemaining() ? null : capabilities;
    }

    private static final class Session {
        Map<String, Integer> capabilities;
        final Map<Integer, Pending> pending = new HashMap<>();

        Session(Map<String, Integer> capabilities) {
            this.capabilities = capabilities;
        }
    }

    private static final class Pending {
        final String action;
        final CompletableFuture<byte[]> result;
        final long sentAt = System.nanoTime();

        Pending(String action, CompletableFuture<byte[]> result) {
            this.action = action;
            this.result = result;
        }
    }
}
