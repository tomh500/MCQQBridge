package top.luotiany1.mcqq.crossplay;

import java.util.concurrent.CompletableFuture;
import java.util.function.BiConsumer;
import java.util.function.BiFunction;
import java.util.function.Consumer;

/** Cross-edition Java messaging API. Register and call from the side's game thread. */
public interface GalApi<Peer> {
    void onEvent(String action, BiConsumer<Peer, byte[]> handler);

    void onRequest(String action, BiFunction<Peer, byte[], byte[]> handler);

    void onReady(Consumer<Peer> handler);

    boolean canSendEvent(Peer peer, String action);

    boolean canRequest(Peer peer, String action);

    /** Returns false when the peer does not advertise this event. */
    boolean sendEvent(Peer peer, String action, byte[] payload);

    /** Fails on unavailable actions, remote errors, timeout, or session change. */
    CompletableFuture<byte[]> request(Peer peer, String action, byte[] payload);
}
