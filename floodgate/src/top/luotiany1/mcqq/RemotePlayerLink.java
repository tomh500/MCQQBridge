package top.luotiany1.mcqq;

import org.geysermc.floodgate.api.link.PlayerLink;
import org.geysermc.floodgate.api.link.LinkRequestResult;
import org.geysermc.floodgate.util.LinkedPlayer;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Properties;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Official Floodgate PlayerLink extension, backed by the QQ binding database. */
public final class RemotePlayerLink implements PlayerLink {
    private final ThreadPoolExecutor workers = new ThreadPoolExecutor(4, 4, 0,
        TimeUnit.SECONDS, new ArrayBlockingQueue<Runnable>(128));
    private String endpoint, token;

    @Override public void load() {
        try {
            Properties props = new Properties();
            try (InputStream stream = Files.newInputStream(Paths.get("plugins/floodgate/mcqq.properties"))) {
                props.load(stream);
            }
            endpoint = props.getProperty("service-url", "http://127.0.0.1:18765").replaceAll("/+$", "");
            token = props.getProperty("proxy-token", "");
            URL url = new URL(endpoint);
            if (token.length() < 32 || token.startsWith("CHANGE_ME")) throw new IllegalArgumentException("Missing token");
            if (!url.getProtocol().equals("https") && !(url.getProtocol().equals("http") &&
                (url.getHost().equals("127.0.0.1") || url.getHost().equals("localhost"))))
                throw new IllegalArgumentException("Remote service requires HTTPS");
        } catch (Exception e) { throw new IllegalStateException("Configure plugins/floodgate/mcqq.properties", e); }
    }

    @Override public CompletableFuture<LinkedPlayer> getLinkedPlayer(UUID bedrockId) {
        return lookup(bedrockId).thenApply(link -> link != null && link.getBedrockId().equals(bedrockId) ? link : null);
    }

    private CompletableFuture<LinkedPlayer> lookup(UUID id) {
        try {
            return CompletableFuture.supplyAsync(() -> {
                HttpURLConnection conn = null;
                try {
                    conn = (HttpURLConnection) new URL(endpoint + "/v1/link?uuid=" + id).openConnection();
                    conn.setConnectTimeout(2000);
                    conn.setReadTimeout(3000);
                    conn.setInstanceFollowRedirects(false);
                    conn.setRequestProperty("Authorization", "Bearer " + token);
                    if (conn.getResponseCode() != 200) throw new IllegalStateException("Mapping API unavailable");
                    ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                    try (InputStream stream = conn.getInputStream()) {
                        int ch;
                        while ((ch = stream.read()) != -1) {
                            if (bytes.size() > 256) throw new IllegalStateException("Invalid mapping response");
                            bytes.write(ch);
                        }
                    }
                    String body = new String(bytes.toByteArray(), StandardCharsets.UTF_8);
                    if (body.equals("none")) return null;
                    String[] fields = body.split("\n", -1);
                    if (fields.length != 3 || !fields[1].matches("[A-Za-z0-9_]{3,16}"))
                        throw new IllegalStateException("Invalid mapping response");
                    return LinkedPlayer.of(fields[1], UUID.fromString(fields[0]), UUID.fromString(fields[2]));
                } catch (Exception e) {
                    // Never turn an outage into an unlinked login with an unexpected UUID.
                    throw new java.util.concurrent.CompletionException(e);
                } finally { if (conn != null) conn.disconnect(); }
            }, workers);
        } catch (java.util.concurrent.RejectedExecutionException e) {
            CompletableFuture<LinkedPlayer> failed = new CompletableFuture<>();
            failed.completeExceptionally(e);
            return failed;
        }
    }

    @Override public CompletableFuture<Boolean> isLinkedPlayer(UUID id) { return lookup(id).thenApply(link -> link != null); }
    private <T> CompletableFuture<T> managedByQQ() {
        CompletableFuture<T> result = new CompletableFuture<>();
        result.completeExceptionally(new UnsupportedOperationException("Use QQ /关联基岩 and Java /qqverify"));
        return result;
    }
    @Override public CompletableFuture<Void> linkPlayer(UUID bedrock, UUID java, String name) { return managedByQQ(); }
    @Override public CompletableFuture<Void> unlinkPlayer(UUID java) { return managedByQQ(); }
    @Override public CompletableFuture<?> createLinkRequest(UUID java, String javaName, String bedrockName) { return managedByQQ(); }
    @Override public CompletableFuture<LinkRequestResult> verifyLinkRequest(UUID bedrock, String javaName, String bedrockName, String code) { return managedByQQ(); }
    @Override public String getName() { return "mcqq"; }
    @Override public boolean isEnabled() { return true; }
    @Override public boolean isAllowLinking() { return false; }
    @Override public long getVerifyLinkTimeout() { return 600; }
    @Override public void stop() { workers.shutdown(); }
}
