package top.luotiany1.mcqq.images.forge112;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.Reader;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Properties;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

final class MediaSource {
    static final int MAX_BYTES = 8 * 1024 * 1024;
    private static final int MAX_URL_LENGTH = 4096;
    private static final String[] QQ_HOSTS = {
        "qq.com", "qq.com.cn", "qpic.cn", "gtimg.cn", "gtimg.com", "idqqimg.com", "qlogo.cn"
    };
    private static final Pattern ESCAPED_PATH_SEPARATOR = Pattern.compile("%(?:25|2e|2f|5c)", Pattern.CASE_INSENSITIVE);
    private final List<URI> bases = new ArrayList<>();
    private final boolean enabled;

    MediaSource(Path file) throws IOException {
        Properties config = new Properties();
        Files.createDirectories(file.getParent());
        if (Files.notExists(file)) {
            Files.write(file, ("# Comma-separated media URL prefixes. Each must end in /.\n"
                + "enabled=true\ntrusted-media-bases=\n").getBytes(StandardCharsets.UTF_8));
        }
        try (Reader reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
            config.load(reader);
        }
        enabled = Boolean.parseBoolean(config.getProperty("enabled", "true").trim());
        for (String value : config.getProperty("trusted-media-bases", "").split(",")) {
            URI base = parse(value.trim());
            if (base != null && base.getRawQuery() == null && base.getRawPath().endsWith("/")) {
                bases.add(base.normalize());
            }
        }
    }

    boolean isEnabled() {
        return enabled;
    }

    URI trustedLink(String value) {
        URI uri = parse(value);
        return uri != null && isTrusted(uri) ? uri : null;
    }

    private static URI parse(String value) {
        if (value == null || value.length() > MAX_URL_LENGTH) return null;
        try {
            URI uri = URI.create(value);
            String path = uri.getRawPath();
            if (uri.getHost() != null && uri.getRawUserInfo() == null && uri.getRawFragment() == null
                && ("https".equals(uri.getScheme()) || "http".equals(uri.getScheme()))
                && path != null && !ESCAPED_PATH_SEPARATOR.matcher(path).find() && uri.equals(uri.normalize())) return uri;
        } catch (IllegalArgumentException ignored) {
            // Leave malformed links to the vanilla chat implementation.
        }
        return null;
    }

    private boolean isTrusted(URI uri) {
        for (URI base : bases) {
            if (uri.getHost().equalsIgnoreCase(base.getHost()) && uri.getScheme().equals(base.getScheme())
                && uri.getPort() == base.getPort() && uri.normalize().getRawPath().startsWith(base.getRawPath())) {
                return true;
            }
        }
        int defaultPort = "https".equals(uri.getScheme()) ? 443 : 80;
        if (uri.getPort() != -1 && uri.getPort() != defaultPort) return false;
        String host = uri.getHost().toLowerCase(Locale.ROOT);
        for (String suffix : QQ_HOSTS) {
            if (host.equals(suffix) || host.endsWith("." + suffix)) return true;
        }
        return false;
    }

    byte[] fetch(URI uri) throws IOException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15);
        for (int hop = 0; hop < 4; hop++) {
            uri = trustedLink(uri.toString());
            if (uri == null) throw new IOException("Untrusted image URL");
            HttpURLConnection connection = (HttpURLConnection) uri.toURL().openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(Math.min(5000, remainingMillis(deadline)));
            connection.setReadTimeout(Math.min(5000, remainingMillis(deadline)));
            connection.setRequestProperty("Accept", "image/png,image/jpeg,image/gif");
            connection.setRequestProperty("Accept-Encoding", "identity");
            try {
                int status = connection.getResponseCode();
                if (status == 301 || status == 302 || status == 303 || status == 307 || status == 308) {
                    String location = connection.getHeaderField("Location");
                    if (location == null || location.length() > MAX_URL_LENGTH) throw new IOException("Missing or invalid redirect");
                    URI target = uri.resolve(location);
                    if ("https".equals(uri.getScheme()) && !"https".equals(target.getScheme())) {
                        throw new IOException("Insecure image redirect");
                    }
                    uri = target;
                    continue;
                }
                String encoding = connection.getContentEncoding();
                if (status != 200 || (encoding != null && !"identity".equalsIgnoreCase(encoding))) {
                    throw new IOException("Invalid image response");
                }
                if (connection.getContentLengthLong() > MAX_BYTES) throw new IOException("Image exceeds byte limit");
                try (InputStream body = connection.getInputStream();
                     ByteArrayOutputStream data = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[8192];
                    while (true) {
                        remainingMillis(deadline);
                        int read = body.read(buffer);
                        if (read == -1) return data.toByteArray();
                        if (read > MAX_BYTES - data.size()) throw new IOException("Image exceeds byte limit");
                        data.write(buffer, 0, read);
                    }
                }
            } finally {
                connection.disconnect();
            }
        }
        throw new IOException("Too many redirects");
    }

    private static int remainingMillis(long deadline) throws IOException {
        long nanos = deadline - System.nanoTime();
        if (Thread.currentThread().isInterrupted() || nanos <= 0) throw new IOException("Image request timed out");
        return (int) Math.max(1, TimeUnit.NANOSECONDS.toMillis(nanos));
    }
}
