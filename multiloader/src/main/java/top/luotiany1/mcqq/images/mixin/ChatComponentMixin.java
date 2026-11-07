package top.luotiany1.mcqq.images.mixin;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.components.ChatComponent;
import net.minecraft.client.multiplayer.chat.GuiMessageSource;
import net.minecraft.client.multiplayer.chat.GuiMessageTag;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MessageSignature;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import top.luotiany1.mcqq.images.ChatImageCore;

@Mixin(ChatComponent.class)
public abstract class ChatComponentMixin {
    @Unique private boolean mcqq$addingPreparedMessage;
    @Shadow(remap=false) private void addMessage(Component component, MessageSignature signature, GuiMessageSource source, GuiMessageTag tag) { throw new AssertionError(); }

    // @Inject has the same annotation ABI on Forge and NeoForge; their
    // @ModifyVariable annotations have incompatible 'at' member types.
    @Inject(method="addMessage(Lnet/minecraft/network/chat/Component;Lnet/minecraft/network/chat/MessageSignature;Lnet/minecraft/client/multiplayer/chat/GuiMessageSource;Lnet/minecraft/client/multiplayer/chat/GuiMessageTag;)V", at=@At("HEAD"), cancellable=true, remap=false)
    private void mcqq$prepare(Component message, MessageSignature signature, GuiMessageSource source, GuiMessageTag tag, CallbackInfo ci) {
        if (mcqq$addingPreparedMessage) return;
        Component prepared=ChatImageCore.INSTANCE.prepare(message);
        if (prepared==message) return;
        mcqq$addingPreparedMessage=true;
        try { addMessage(prepared,signature,source,tag); }
        finally { mcqq$addingPreparedMessage=false; }
        ci.cancel();
    }
    @Inject(method="extractRenderState(Lnet/minecraft/client/gui/GuiGraphicsExtractor;Lnet/minecraft/client/gui/Font;IIILnet/minecraft/client/gui/components/ChatComponent$DisplayMode;Z)V", at=@At("TAIL"), remap=false)
    private void mcqq$draw(GuiGraphicsExtractor graphics, Font font, int ticks, int mouseX, int mouseY, ChatComponent.DisplayMode mode, boolean cursor, CallbackInfo ci) {
        ChatImageCore.INSTANCE.render(graphics);
    }
}
