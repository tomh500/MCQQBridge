package top.luotiany1.mcqq.images;

import java.awt.AlphaComposite;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import javax.imageio.ImageIO;
import javax.imageio.ImageReader;
import javax.imageio.metadata.IIOMetadataNode;
import javax.imageio.stream.ImageInputStream;

/** Bounded decoding with GIF disposal/compositing; never runs on Minecraft's render thread. */
public final class ImageFrames {
    public record Frame(BufferedImage image, int milliseconds) { }
    private ImageFrames() { }
    public static List<Frame> decode(byte[] data) throws IOException {
        try (ImageInputStream input = ImageIO.createImageInputStream(new ByteArrayInputStream(data))) {
            var readers = ImageIO.getImageReaders(input);
            if (!readers.hasNext()) throw new IOException("Unsupported image");
            ImageReader reader = readers.next();
            try {
                reader.setInput(input);
                int width = reader.getWidth(0), height = reader.getHeight(0);
                boolean gif = reader.getFormatName().equalsIgnoreCase("gif");
                if (gif) {
                    var metadata = reader.getStreamMetadata();
                    if (metadata != null) {
                        var tree = (IIOMetadataNode) metadata.getAsTree("javax_imageio_gif_stream_1.0");
                        var descriptors = tree.getElementsByTagName("LogicalScreenDescriptor");
                        if (descriptors.getLength() > 0) {
                            var node = (IIOMetadataNode) descriptors.item(0);
                            width = Integer.parseInt(node.getAttribute("logicalScreenWidth"));
                            height = Integer.parseInt(node.getAttribute("logicalScreenHeight"));
                        }
                    }
                }
                if (width <= 0 || height <= 0 || width > 8192 || height > 8192 || (long) width * height > 16_777_216)
                    throw new IOException("Image dimensions too large");
                int count = gif ? Math.min(48, reader.getNumImages(true)) : 1;
                BufferedImage canvas = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
                List<Frame> frames = new ArrayList<>();
                long pixels = 0;
                for (int i = 0; i < count; i++) {
                    int x = 0, y = 0, delay = 100;
                    String disposal = "none";
                    if (gif) {
                        var tree = (IIOMetadataNode) reader.getImageMetadata(i).getAsTree("javax_imageio_gif_image_1.0");
                        var descriptor = (IIOMetadataNode) tree.getElementsByTagName("ImageDescriptor").item(0);
                        x = Integer.parseInt(descriptor.getAttribute("imageLeftPosition"));
                        y = Integer.parseInt(descriptor.getAttribute("imageTopPosition"));
                        var controls = tree.getElementsByTagName("GraphicControlExtension");
                        if (controls.getLength() > 0) {
                            var control = (IIOMetadataNode) controls.item(0);
                            delay = Math.max(40, Integer.parseInt(control.getAttribute("delayTime")) * 10);
                            disposal = control.getAttribute("disposalMethod");
                        }
                    }
                    BufferedImage previous = disposal.equals("restoreToPrevious") ? copy(canvas, width, height) : null;
                    BufferedImage next = reader.read(i);
                    Graphics2D graphics = canvas.createGraphics();
                    graphics.drawImage(next, x, y, null); graphics.dispose();
                    double scale = Math.min(1, 512.0 / Math.max(width, height));
                    int w = Math.max(1, (int)(width * scale)), h = Math.max(1, (int)(height * scale));
                    pixels += (long)w * h;
                    if (pixels > 8_388_608) break;
                    frames.add(new Frame(copy(canvas, w, h), delay));
                    if (disposal.equals("restoreToBackgroundColor")) {
                        graphics = canvas.createGraphics(); graphics.setComposite(AlphaComposite.Clear);
                        graphics.fillRect(x, y, next.getWidth(), next.getHeight()); graphics.dispose();
                    } else if (previous != null) canvas = previous;
                }
                if (frames.isEmpty()) throw new IOException("Empty image");
                return frames;
            } finally { reader.dispose(); }
        }
    }
    private static BufferedImage copy(BufferedImage source, int width, int height) {
        var result = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics = result.createGraphics();
        graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        graphics.drawImage(source, 0, 0, width, height, null); graphics.dispose();
        return result;
    }
}
