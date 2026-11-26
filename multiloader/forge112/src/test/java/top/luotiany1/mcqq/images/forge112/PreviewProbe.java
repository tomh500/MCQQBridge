package top.luotiany1.mcqq.images.forge112;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicInteger;
import javax.imageio.ImageIO;

public final class PreviewProbe {
    public static void main(String[] args) throws Exception {
        ByteArrayOutputStream png = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(16, 8, BufferedImage.TYPE_INT_ARGB), "png", png);
        byte[] image = png.toByteArray();
        HttpServer http = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicInteger outOfScopeRequests = new AtomicInteger();
        http.createContext("/mcqq-media/image", request -> send(request, image));
        http.createContext("/mcqq-media/accepted", request -> redirect(request, "/mcqq-media/image"));
        http.createContext("/mcqq-media/rejected", request -> redirect(request, "/other/image"));
        http.createContext("/mcqq-media/loop", request -> redirect(request, "/mcqq-media/loop"));
        http.createContext("/mcqq-media/too-large", request -> {
            request.sendResponseHeaders(200, 0);
            try {
                byte[] chunk = new byte[8192];
                for (int sent = 0; sent <= MediaSource.MAX_BYTES; sent += chunk.length) request.getResponseBody().write(chunk);
            } catch (IOException expected) {
                // The downloader closes the connection when it exceeds the limit.
            } finally {
                request.close();
            }
        });
        http.createContext("/other/image", request -> {
            outOfScopeRequests.incrementAndGet();
            send(request, image);
        });
        http.start();
        Path configDir = Files.createTempDirectory("mcqq-forge112-media");
        Path config = configDir.resolve("mcqq-images.properties");
        try {
            String host = "http://127.0.0.1:" + http.getAddress().getPort();
            Files.write(config, ("trusted-media-bases=" + host + "/mcqq-media/\n").getBytes(StandardCharsets.UTF_8));
            MediaSource media = new MediaSource(config);
            check(media.trustedLink("https://multimedia.nt.qq.com/download?app=x") != null, "QQ host");
            check(media.trustedLink("https://notqq.com/image") == null, "lookalike host");
            check(media.trustedLink("https://example.com@multimedia.nt.qq.com/download") == null, "user info");
            check(media.trustedLink("https://qq.com:444/image") == null, "nondefault port");
            check(media.trustedLink(host + "/mcqq-media-not/image") == null, "base path boundary");
            check(media.trustedLink(host + "/mcqq-media/../other/image") == null, "dot segment");
            check(media.trustedLink(host + "/mcqq-media/%2e%2e/other/image") == null, "encoded dot segment");
            check(media.trustedLink(host + "/mcqq-media/image#fragment") == null, "fragment");

            ImageFrames.Frame frame = ImageFrames.decode(media.fetch(URI.create(host + "/mcqq-media/accepted"))).get(0);
            check(frame.image.getWidth() == 16 && frame.image.getHeight() == 8, "PNG via allowed redirect");
            // Minimal GIF with two image descriptors to exercise Java 8 frame compositing.
            ByteArrayOutputStream gif = new ByteArrayOutputStream();
            javax.imageio.ImageWriter writer = ImageIO.getImageWritersByFormatName("gif").next();
            try (javax.imageio.stream.ImageOutputStream output = new javax.imageio.stream.MemoryCacheImageOutputStream(gif)) {
                writer.setOutput(output);
                writer.prepareWriteSequence(null);
                for (int i = 0; i < 2; i++) {
                    BufferedImage gifFrame = new BufferedImage(4, 3, BufferedImage.TYPE_INT_RGB);
                    gifFrame.setRGB(0, 0, i == 0 ? 0xffff0000 : 0xff00ff00);
                    writer.writeToSequence(new javax.imageio.IIOImage(gifFrame, null, null), null);
                }
                writer.endWriteSequence();
            } finally {
                writer.dispose();
            }
            java.util.List<ImageFrames.Frame> frames = ImageFrames.decode(gif.toByteArray());
            check(frames.size() == 2 && frames.get(0).image.getRGB(0, 0) != frames.get(1).image.getRGB(0, 0),
                "two distinct GIF frames");
            expectFailure(() -> media.fetch(URI.create(host + "/mcqq-media/rejected")));
            check(outOfScopeRequests.get() == 0, "out-of-scope redirect never fetched");
            expectFailure(() -> media.fetch(URI.create(host + "/mcqq-media/loop")));
            expectFailure(() -> media.fetch(URI.create(host + "/mcqq-media/too-large")));
            expectFailure(() -> ImageFrames.decode(new byte[] {1, 2, 3}));
            ByteArrayOutputStream oversized = new ByteArrayOutputStream();
            ImageIO.write(new BufferedImage(8193, 1, BufferedImage.TYPE_INT_RGB), "png", oversized);
            expectFailure(() -> ImageFrames.decode(oversized.toByteArray()));
        } finally {
            http.stop(0);
            Files.deleteIfExists(config);
            Files.deleteIfExists(configDir);
        }
        System.out.println("Forge 1.12.2 image media probe passed");
    }

    private static void send(HttpExchange exchange, byte[] image) throws IOException {
        try {
            exchange.sendResponseHeaders(200, image.length);
            exchange.getResponseBody().write(image);
        } finally {
            exchange.close();
        }
    }

    private static void redirect(HttpExchange exchange, String location) throws IOException {
        try {
            exchange.getResponseHeaders().add("Location", location);
            exchange.sendResponseHeaders(302, -1);
        } finally {
            exchange.close();
        }
    }

    private static void check(boolean condition, String name) {
        if (!condition) throw new AssertionError(name);
    }

    private static void expectFailure(IoAction action) throws IOException {
        try {
            action.run();
            throw new AssertionError("Expected rejection");
        } catch (IOException expected) {
            // Expected.
        }
    }

    @FunctionalInterface
    private interface IoAction {
        void run() throws IOException;
    }
}
