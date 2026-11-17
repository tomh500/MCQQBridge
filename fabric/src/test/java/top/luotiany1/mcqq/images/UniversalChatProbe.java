package top.luotiany1.mcqq.images;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.URI;
import net.minecraft.client.StringSplitter;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.Style;
import net.minecraft.resources.Identifier;
public final class UniversalChatProbe {
  public static final class FakeEvent {
    public static final Identifier DEFAULT_PHASE=Identifier.fromNamespaceAndPath("fabric", "default");
    Identifier before,after,registered; Object callback;
    public void addPhaseOrdering(Identifier first,Identifier second) { before=first; after=second; }
    public void register(Identifier phase,Object listener) { registered=phase; callback=listener; }
    public void register(Object listener) { callback=listener; }
  }
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
    int actualLeft=com.mojang.blaze3d.platform.InputConstants.class.getField("MOUSE_BUTTON_LEFT").getInt(null);
    int expectedLeft=version.equals("26.3") ? 1 : 0;
    if(actualLeft!=expectedLeft)throw new AssertionError("Unexpected mouse mapping in "+version+": "+actualLeft);
    int actualEscape=com.mojang.blaze3d.platform.InputConstants.class.getField("KEY_ESCAPE").getInt(null);
    if(actualEscape!=(version.equals("26.3") ? 41 : 256))throw new AssertionError("Unexpected escape mapping in "+version+": "+actualEscape);
    Field left=UniversalImages.class.getDeclaredField("leftButton"); left.setAccessible(true); left.setInt(mod,actualLeft);
    FakeEvent event=new FakeEvent(); Object listener=new Object();
    Method register=UniversalImages.class.getDeclaredMethod("registerViewerListener",Object.class,Class.class,Object.class); register.setAccessible(true);
    register.invoke(mod,event,FakeEvent.class,listener);
    if(event.before==null || !event.before.equals(event.registered) || !FakeEvent.DEFAULT_PHASE.equals(event.after) || event.callback!=listener)
      throw new AssertionError("Viewer must register before the default event phase");
    Method prepare=UniversalImages.class.getDeclaredMethod("prepare",Object.class); prepare.setAccessible(true);
    var original=Component.literal("[example group] sender: <faceType=6,faceId=0,ext=opaque>").append(Component.literal(" [图片]").setStyle(Style.EMPTY.withClickEvent(new ClickEvent.OpenUrl(URI.create("https://gchat.qpic.cn/example.png")))));
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
    if(!original.getString().equals("[example group] sender: <faceType=6,faceId=0,ext=opaque> [图片]"))throw new AssertionError("Original component changed");
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
    Field ow=previewType.getDeclaredField("originalWidth"), oh=previewType.getDeclaredField("originalHeight");
    ow.setAccessible(true); oh.setAccessible(true); ow.setInt(preview,640); oh.setInt(preview,480);
    String url="https://gchat.qpic.cn/example.png"; previews.put(url,preview);
    Class<?> hitType=Class.forName("top.luotiany1.mcqq.images.UniversalImages$Hit");
    var hitCtor=hitType.getDeclaredConstructor(int.class,int.class,int.class,int.class,URI.class); hitCtor.setAccessible(true);
    Field hitsField=UniversalImages.class.getDeclaredField("hits"); hitsField.setAccessible(true);
    ((java.util.List)hitsField.get(mod)).add(hitCtor.newInstance(10,20,100,60,URI.create(url)));
    Method click=UniversalImages.class.getDeclaredMethod("handleClick",double.class,double.class,int.class); click.setAccessible(true);
    if((boolean)click.invoke(mod,50d,40d,actualLeft==0 ? 1 : 0))throw new AssertionError("Other button opened viewer");
    if((boolean)click.invoke(mod,200d,200d,actualLeft))throw new AssertionError("Click outside preview was consumed");
    if(!(boolean)click.invoke(mod,50d,40d,actualLeft))throw new AssertionError("Click inside preview was not handled");
    Field viewerField=UniversalImages.class.getDeclaredField("viewer"); viewerField.setAccessible(true);
    if(viewerField.get(mod)==null)throw new AssertionError("Preview click did not open viewer");
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
