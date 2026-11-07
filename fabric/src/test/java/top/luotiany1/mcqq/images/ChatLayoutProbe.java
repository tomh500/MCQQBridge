package top.luotiany1.mcqq.images;
import java.util.Optional;
import net.minecraft.client.StringSplitter;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.Style;
public final class ChatLayoutProbe {
  public static void main(String[] args) {
    String marker="mcqq-image:test";
    var msg=Component.literal("sender: [图片]");
    for(int i=0;i<7;i++) msg.append(Component.literal("\n\u00a0").setStyle(Style.EMPTY.withInsertion(marker)));
    var lines=new StringSplitter((codepoint,style)->6f).splitLines(msg,300,Style.EMPTY);
    int marked=0;
    for(var line:lines) {
      boolean[] found={false};
      net.minecraft.locale.Language.getInstance().getVisualOrder(line).accept((index,style,codepoint)->{
        if(marker.equals(style.getInsertion())) found[0]=true;
        return true;
      });
      if(found[0]) marked++;
    }
    if(marked!=7) throw new AssertionError("Expected 7 marked chat lines, got "+marked+" from "+lines.size());
    System.out.println("PASS: Minecraft chat wrapping preserves all 7 image marker lines");
  }
}
