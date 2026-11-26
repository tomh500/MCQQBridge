package top.luotiany1.mcqq.crossplay.mixin;

import com.mojang.blaze3d.vertex.PoseStack;
import net.minecraft.client.renderer.FirstPersonHandsAndItemsRenderer;
import net.minecraft.client.renderer.SubmitNodeCollector;
import net.minecraft.client.renderer.state.level.FirstPersonHandsAndItemsRenderState;
import net.minecraft.client.renderer.state.level.PlayerRenderState;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.ItemStack;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import top.luotiany1.mcqq.crossplay.SwordGuardClient;

@Mixin(FirstPersonHandsAndItemsRenderer.class)
abstract class GuardHandMixin {
    @Inject(method = "submitArmWithItem", at = @At(value = "INVOKE", ordinal = 1, target =
            "Lnet/minecraft/client/renderer/item/ItemStackRenderState;submit(Lcom/mojang/blaze3d/vertex/PoseStack;"
                    + "Lnet/minecraft/client/renderer/SubmitNodeCollector;III)V"))
    private void applySwordGuard(PlayerRenderState player, FirstPersonHandsAndItemsRenderState hands,
            float partialTick, float pitch, InteractionHand hand, float swing, ItemStack item, float equipProgress,
            PoseStack pose, SubmitNodeCollector output, int light, CallbackInfo callback) {
        if (hand == InteractionHand.MAIN_HAND && player.avatarRenderState != null) {
            SwordGuardClient.applyPose(pose, player.avatarRenderState.mainArm, item);
        }
    }
}
