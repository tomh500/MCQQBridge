package top.luotiany1.mcqq.crossplay;

import com.mojang.blaze3d.vertex.PoseStack;
import net.minecraft.client.Minecraft;
import net.minecraft.tags.ItemTags;
import net.minecraft.world.entity.HumanoidArm;
import net.minecraft.world.item.ItemStack;
import org.joml.Matrix4f;

public final class SwordGuardClient {
    private static SwordGuardSession<Minecraft> guard;

    SwordGuardClient(GalApi<Minecraft> api) {
        guard = new SwordGuardSession<>(api);
    }

    void register() {
        guard.register();
    }

    void tick(Minecraft client) {
        guard.tick(client, client.player != null && client.getConnection() != null
                && !client.player.isSpectator() && !client.player.isDeadOrDying()
                && client.isWindowActive() && client.gui.screen() == null
                && client.options.keyUse.isDown() && isSword(client.player.getMainHandItem()));
    }

    void reset() {
        guard.reset();
    }

    public static void applyPose(PoseStack pose, HumanoidArm arm, ItemStack item) {
        if (guard == null || !guard.showPose() || !isSword(item)) {
            return;
        }
        float side = arm == HumanoidArm.RIGHT ? 1.0F : -1.0F;
        pose.translate(-0.28F * side, 0.16F, 0.03F);
        pose.mulPose(new Matrix4f().rotateY((float) Math.toRadians(-34.0F * side))
                .rotateX((float) Math.toRadians(-41.0F))
                .rotateZ((float) Math.toRadians(49.0F * side)));
    }

    private static boolean isSword(ItemStack item) {
        return !item.isEmpty() && item.typeHolder().is(ItemTags.SWORDS);
    }
}
