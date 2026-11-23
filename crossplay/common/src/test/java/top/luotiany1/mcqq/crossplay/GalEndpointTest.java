package top.luotiany1.mcqq.crossplay;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

public final class GalEndpointTest {
    private static final String PEER = "player";
    private static final String CLIENT_ACTION = "test:client";
    private static final String SERVER_ACTION = "test:server";
    private static final byte[] DATA = "验证".getBytes(StandardCharsets.UTF_8);

    private static void check(boolean condition) {
        if (!condition) {
            throw new AssertionError("MasterGAL test condition failed");
        }
    }

    public static void main(String[] args) {
        AtomicReference<GalEndpoint<String>> client = new AtomicReference<>();
        AtomicBoolean drop = new AtomicBoolean();
        GalEndpoint<String> server = new GalEndpoint<>(false,
                (peer, data) -> client.get().receive(peer, data),
                failure -> { throw failure; });
        client.set(new GalEndpoint<>(true, (peer, data) -> {
            if (!drop.get()) {
                server.receive(peer, data);
            }
        }, failure -> { throw failure; }));
        AtomicBoolean clientEvent = new AtomicBoolean();
        AtomicBoolean serverEvent = new AtomicBoolean();
        server.onRequest(SERVER_ACTION, (peer, data) -> data);
        client.get().onRequest(CLIENT_ACTION, (peer, data) -> data);
        client.get().onRequest("test:rejected", (peer, data) -> null);
        client.get().onEvent(CLIENT_ACTION, (peer, data) -> clientEvent.set(Arrays.equals(DATA, data)));
        server.onEvent(SERVER_ACTION, (peer, data) -> serverEvent.set(Arrays.equals(DATA, data)));

        check(!server.canRequest(PEER, CLIENT_ACTION));
        client.get().begin(PEER);
        check(server.canRequest(PEER, CLIENT_ACTION) && client.get().canRequest(PEER, SERVER_ACTION));
        check(client.get().sendEvent(PEER, SERVER_ACTION, DATA) && serverEvent.get());
        check(server.sendEvent(PEER, CLIENT_ACTION, DATA) && clientEvent.get());
        check(Arrays.equals(server.request(PEER, CLIENT_ACTION, DATA).join(), DATA));
        check(Arrays.equals(client.get().request(PEER, SERVER_ACTION, DATA).join(), DATA));
        check(server.request(PEER, "test:rejected", DATA).isCompletedExceptionally());
        check(!server.sendEvent(PEER, "test:unknown", DATA));

        drop.set(true);
        CompletableFuture<byte[]> pending = client.get().request(PEER, SERVER_ACTION, DATA);
        check(!pending.isDone());
        client.get().receive(PEER, GalPacket.reset());
        check(pending.isCompletedExceptionally() && !client.get().canRequest(PEER, SERVER_ACTION));
        drop.set(false);
        server.close(PEER);
        client.get().begin(PEER);
        check(client.get().canRequest(PEER, SERVER_ACTION));
        check(GalPacket.decode(new byte[GalPacket.MAX_FRAME + 1]) == null);
        check(GalPacket.decode(new byte[] {1, 4, 0, 0, 0, 0, 1, 65}) == null);
        System.out.println("MasterGAL capability exchange, bidirectional messages, errors, and session reset passed");
    }
}
