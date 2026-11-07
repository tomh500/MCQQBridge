package top.luotiany1.mcqq.images;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.URI;
import net.minecraft.client.StringSplitter;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.Style;
public final class UniversalChatProbe {
  public static final class FakeChat {
    private int chatScrollbarPos=4;
    private int refreshes;
    private void refreshTrimmedMessages() { refreshes++; chatScrollbarPos=0; }
  }
  @SuppressWarnings({"unchecked", "rawtypes"})
  public static void main(String[] args) throws Exception {
    String version=args[0];
    var mod=new UniversalImages();
    Field adapter=UniversalImages.class.getDeclaredField("bridge"); adapter.setAccessible(true); adapter.set(mod,new Bridge(version));
    Method prepare=UniversalImages.class.getDeclaredMethod("prepare",Object.class); prepare.setAccessible(true);
    var original=Component.literal("[example group] sender: <faceType=6,faceId=0,ext=opaque>").append(Component.literal("[图片]").setStyle(Style.EMPTY.withClickEvent(new ClickEvent.OpenUrl(URI.create("https://gchat.qpic.cn/example.png")))));
    Component result=(Component)prepare.invoke(mod,original);
    var lines=new StringSplitter((codepoint,style)->6f).splitLines(result,300,Style.EMPTY);
    int[] marked={0};
    for(var line:lines) {
      boolean[] found={false};
      net.minecraft.locale.Language.getInstance().getVisualOrder(line).accept((index,style,codepoint)->{ if(style.getInsertion()!=null && style.getInsertion().startsWith("mcqq-image:"))found[0]=true; return true; });
      if(found[0])marked[0]++;
    }
    if(marked[0]!=7)throw new AssertionError("Expected 7 marked image lines, got "+marked[0]);
    if(result.getString().contains("faceType"))throw new AssertionError("Raw face metadata remained visible");
    if(!original.getString().equals("[example group] sender: <faceType=6,faceId=0,ext=opaque>[图片]"))throw new AssertionError("Original component changed");
    Field slotsField=UniversalImages.class.getDeclaredField("labelSlots"); slotsField.setAccessible(true);
    var slots=(java.util.Map<?,?>)slotsField.get(mod);
    if(slots.size()!=1)throw new AssertionError("Expected one recoverable fallback link");
    Object slot=slots.values().iterator().next();
    Method show=slot.getClass().getDeclaredMethod("show",boolean.class); show.setAccessible(true);
    show.invoke(slot,false);
    if(result.getString().contains("[图片]"))throw new AssertionError("Rendered link was not hidden");
    show.invoke(slot,true);
    if(!result.getString().contains("[图片]"))throw new AssertionError("Fallback link was not restored");
    Field previewsField=UniversalImages.class.getDeclaredField("previews"); previewsField.setAccessible(true);
    var previews=(java.util.Map)previewsField.get(mod);
    Class<?> previewType=Class.forName("top.luotiany1.mcqq.images.UniversalImages$Preview");
    var ctor=previewType.getDeclaredConstructor(String.class); ctor.setAccessible(true); Object preview=ctor.newInstance("");
    Field frames=previewType.getDeclaredField("frames"); frames.setAccessible(true); ((java.util.List)frames.get(preview)).add(new Object());
    String url="https://gchat.qpic.cn/example.png"; previews.put(url,preview);
    Field drawnField=UniversalImages.class.getDeclaredField("drawn"); drawnField.setAccessible(true);
    var drawn=(java.util.Set)drawnField.get(mod);
    Method sync=UniversalImages.class.getDeclaredMethod("syncLabels",Object.class,String.class,int.class); sync.setAccessible(true);
    FakeChat chat=new FakeChat();
    sync.invoke(mod,chat,FakeChat.class.getName(),4);
    if(!result.getString().contains("[图片]"))throw new AssertionError("Undrawn image hid its fallback");
    drawn.add(url); sync.invoke(mod,chat,FakeChat.class.getName(),4);
    if(result.getString().contains("[图片]") || chat.chatScrollbarPos!=4)throw new AssertionError("Drawn image did not hide link while preserving scroll");
    Field failed=previewType.getDeclaredField("failed"); failed.setAccessible(true); failed.setBoolean(preview,true);
    sync.invoke(mod,chat,FakeChat.class.getName(),4);
    if(!result.getString().contains("[图片]"))throw new AssertionError("Failed image did not restore its link");
    failed.setBoolean(preview,false); sync.invoke(mod,chat,FakeChat.class.getName(),4);
    previews.remove(url); sync.invoke(mod,chat,FakeChat.class.getName(),4);
    if(!result.getString().contains("[图片]") || chat.chatScrollbarPos!=4 || chat.refreshes!=4)throw new AssertionError("Eviction did not restore link and scroll");
    System.out.println("PASS: "+version+" universal adapter preserves click components and reserves seven marked chat lines");
  }
}
