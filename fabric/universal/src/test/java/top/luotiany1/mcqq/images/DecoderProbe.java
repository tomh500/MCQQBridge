package top.luotiany1.mcqq.images;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import javax.imageio.ImageIO;
import javax.imageio.ImageTypeSpecifier;
import javax.imageio.IIOImage;
import javax.imageio.metadata.IIOMetadataNode;
import javax.imageio.stream.MemoryCacheImageOutputStream;

public final class DecoderProbe {
    public static void main(String[] args) throws Exception {
        BufferedImage image=new BufferedImage(4,3,BufferedImage.TYPE_INT_ARGB); image.setRGB(0,0,0xFFFF0022);
        ByteArrayOutputStream png=new ByteArrayOutputStream(); ImageIO.write(image,"png",png);
        var decoded=ImageFrames.decode(png.toByteArray());
        if (decoded.size()!=1 || decoded.getFirst().image().getRGB(0,0)!=0xFFFF0022) throw new AssertionError("PNG color decoding failed");
        ByteArrayOutputStream gif=new ByteArrayOutputStream();
        var writer=ImageIO.getImageWritersByFormatName("gif").next();
        try (var stream=new MemoryCacheImageOutputStream(gif)) {
            writer.setOutput(stream); writer.prepareWriteSequence(null);
            for (int color : new int[]{0xFFFF0000,0xFF0000FF}) {
                BufferedImage frame=new BufferedImage(4,3,BufferedImage.TYPE_INT_ARGB);
                for(int y=0;y<3;y++) for(int x=0;x<4;x++) frame.setRGB(x,y,color);
                var metadata=writer.getDefaultImageMetadata(new ImageTypeSpecifier(frame),null);
                var tree=(IIOMetadataNode)metadata.getAsTree("javax_imageio_gif_image_1.0");
                var control=(IIOMetadataNode)tree.getElementsByTagName("GraphicControlExtension").item(0);
                control.setAttribute("delayTime","5"); metadata.setFromTree("javax_imageio_gif_image_1.0",tree);
                writer.writeToSequence(new IIOImage(frame,null,metadata),null);
            }
            writer.endWriteSequence();
        } finally { writer.dispose(); }
        decoded=ImageFrames.decode(gif.toByteArray());
        if(decoded.size()!=2 || decoded.getFirst().milliseconds()!=50 || decoded.get(1).image().getRGB(0,0)!=0xFF0000FF)
            throw new AssertionError("Animated GIF decoding failed");
        BufferedImage huge=new BufferedImage(9000,1,BufferedImage.TYPE_INT_ARGB);
        ByteArrayOutputStream data=new ByteArrayOutputStream(); ImageIO.write(huge,"png",data);
        try { ImageFrames.decode(data.toByteArray()); throw new AssertionError("Image dimension limit not enforced"); }
        catch(java.io.IOException expected) { }
        System.out.println("PASS: PNG colors, animated GIF frames/timing, oversized-image rejection");
    }
}
