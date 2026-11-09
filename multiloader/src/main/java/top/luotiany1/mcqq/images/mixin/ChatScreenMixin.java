package top.luotiany1.mcqq.images.mixin;

import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.screens.ChatScreen;
import net.minecraft.client.input.MouseButtonEvent;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
import top.luotiany1.mcqq.images.ChatImageCore;

@Mixin(ChatScreen.class)
public abstract class ChatScreenMixin extends Screen {
    protected ChatScreenMixin(Component title) { super(title); }
    @Inject(method="mouseClicked", at=@At("HEAD"), cancellable=true, remap=false)
    private void mcqq$click(MouseButtonEvent event, boolean doubled, CallbackInfoReturnable<Boolean> result) {
        if (ChatImageCore.INSTANCE.click(event.x(),event.y(),event.button())) result.setReturnValue(true);
    }
    @Inject(method="extractRenderState", at=@At("TAIL"), remap=false)
    private void mcqq$viewer(GuiGraphicsExtractor graphics, int mouseX, int mouseY, float delta, CallbackInfo ci) {
        ChatImageCore.INSTANCE.renderViewer(graphics,mouseX,mouseY);
    }
    @Inject(method="mouseScrolled", at=@At("HEAD"), cancellable=true, remap=false)
    private void mcqq$scroll(double x,double y,double horizontal,double vertical,CallbackInfoReturnable<Boolean> result) {
        if(ChatImageCore.INSTANCE.scrollViewer(x,y,vertical))result.setReturnValue(true);
    }
    @Inject(method="keyPressed", at=@At("HEAD"), cancellable=true, remap=false)
    private void mcqq$key(KeyEvent event,CallbackInfoReturnable<Boolean> result) {
        if(event.key()==256 && ChatImageCore.INSTANCE.dismissViewer())result.setReturnValue(true);
    }
    @Override public boolean mouseReleased(MouseButtonEvent event) {
        if(ChatImageCore.INSTANCE.releaseViewer())return true;
        return super.mouseReleased(event);
    }
    @Inject(method="removed", at=@At("TAIL"), remap=false)
    private void mcqq$close(CallbackInfo ci) { ChatImageCore.INSTANCE.closeViewer(); }
}
