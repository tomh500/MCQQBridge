package top.luotiany1.mcqq.crossplay.mixin;

import com.mojang.blaze3d.vertex.PoseStack;
import net.minecraft.client.player.AbstractClientPlayer;
import net.minecraft.client.renderer.ItemInHandRenderer;
import net.minecraft.client.renderer.SubmitNodeCollector;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.ItemStack;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import top.luotiany1.mcqq.crossplay.SwordGuardClient;

@Mixin(ItemInHandRenderer.class)
abstract class GuardHandMixin {
    @Inject(method = "submitArmWithItem", at = @At(value = "INVOKE", ordinal = 1, target =
            "Lnet/minecraft/client/renderer/ItemInHandRenderer;renderItem(Lnet/minecraft/world/entity/LivingEntity;"
                    + "Lnet/minecraft/world/item/ItemStack;Lnet/minecraft/world/item/ItemDisplayContext;"
                    + "Lcom/mojang/blaze3d/vertex/PoseStack;Lnet/minecraft/client/renderer/SubmitNodeCollector;I)V"))
    private void applySwordGuard(AbstractClientPlayer player, float partialTick, float pitch, InteractionHand hand,
            float swing, ItemStack item, float equipProgress, PoseStack pose, SubmitNodeCollector output,
            int light, CallbackInfo callback) {
        if (hand == InteractionHand.MAIN_HAND) {
            SwordGuardClient.applyPose(pose, player.getMainArm(), item);
        }
    }
}
