package top.luotiany1.mcqq.images.forge112;

import java.awt.image.BufferedImage;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.net.URI;
import net.minecraft.client.Minecraft;
import net.minecraft.client.renderer.texture.DynamicTexture;
import net.minecraft.util.ResourceLocation;

/** The main thread owns entries and textures. A bounded worker only fetches and decodes. */
final class PreviewCache {
    private static final int MAX_ENTRIES = 8;
    private final Map<URI, Preview> entries = new LinkedHashMap<>(16, 0.75F, true);
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
        new ArrayBlockingQueue<>(MAX_ENTRIES), task -> {
            Thread thread = new Thread(task, "MCQQ image download");
            thread.setDaemon(true);
            return thread;
        });
    private final Minecraft client;
    private final MediaSource media;

    PreviewCache(Minecraft client, MediaSource media) {
        this.client = client;
        this.media = media;
    }

    Preview get(URI uri) {
        return entries.get(uri);
    }

    Preview request(URI uri, Set<URI> visible) {
        Preview existing = entries.get(uri);
        if (existing != null) return existing;
        if (entries.size() >= MAX_ENTRIES) {
            Iterator<Map.Entry<URI, Preview>> iterator = entries.entrySet().iterator();
            while (iterator.hasNext()) {
                Map.Entry<URI, Preview> candidate = iterator.next();
                if (visible.contains(candidate.getKey())) continue;
                candidate.getValue().dispose();
                iterator.remove();
                break;
            }
            if (entries.size() >= MAX_ENTRIES) return null;
        }
        FutureTask<List<ImageFrames.Frame>> pending = new FutureTask<>(() -> ImageFrames.decode(media.fetch(uri)));
        Preview preview = new Preview(pending);
        entries.put(uri, preview);
        worker.execute(pending);
        return preview;
    }

    void clear() {
        for (Preview preview : entries.values()) preview.dispose();
        entries.clear();
    }

    final class Preview {
        private FutureTask<List<ImageFrames.Frame>> pending;
        private List<ImageFrames.Frame> frames;
        private DynamicTexture texture;
        private ResourceLocation location;
        private long start;
        private int duration;
        private int uploaded = -1;

        Preview(FutureTask<List<ImageFrames.Frame>> pending) {
            this.pending = pending;
        }

        boolean ready() {
            if (pending != null && pending.isDone()) {
                try {
                    frames = pending.get();
                    for (ImageFrames.Frame frame : frames) duration += frame.milliseconds;
                    start = System.nanoTime();
                } catch (ExecutionException ignored) {
                    // Keep the vanilla link and remember the failure until the entry is evicted.
                } catch (InterruptedException ignored) {
                    Thread.currentThread().interrupt();
                }
                pending = null;
            }
            return frames != null;
        }

        int width() {
            return frames.get(0).image.getWidth();
        }

        int height() {
            return frames.get(0).image.getHeight();
        }

        void bind() {
            if (texture == null) {
                texture = new DynamicTexture(width(), height());
                location = client.getTextureManager().getDynamicTextureLocation("mcqq_image", texture);
            }
            int offset = (int) (TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - start) % duration);
            int index = 0;
            while (offset >= frames.get(index).milliseconds) offset -= frames.get(index++).milliseconds;
            if (index != uploaded) {
                BufferedImage image = frames.get(index).image;
                int width = image.getWidth();
                image.getRGB(0, 0, width, image.getHeight(), texture.getTextureData(), 0, width);
                texture.updateDynamicTexture();
                uploaded = index;
            }
            client.getTextureManager().bindTexture(location);
        }

        void dispose() {
            if (pending != null) {
                pending.cancel(true);
                worker.remove(pending);
            }
            if (location != null) client.getTextureManager().deleteTexture(location);
        }
    }
}
