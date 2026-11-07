package top.luotiany1.mcqq.images.mixin;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.screens.Screen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import top.luotiany1.mcqq.images.ChatImageCore;
@Mixin(Minecraft.class)
public abstract class MinecraftMixin {
    @Inject(method="disconnect(Lnet/minecraft/client/gui/screens/Screen;ZZ)V", at=@At("HEAD"), remap=false)
    private void mcqq$clear(Screen screen, boolean transferring, boolean waiting, CallbackInfo ci) { ChatImageCore.INSTANCE.clear(); }
}
