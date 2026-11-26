package top.luotiany1.mcqq.images.forge112;

import java.io.IOException;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.common.event.FMLPreInitializationEvent;

@Mod(modid = "mcqq_images", name = "MCQQ Images", version = "1.0.0",
    acceptedMinecraftVersions = "[1.12.2]", acceptableRemoteVersions = "*", clientSideOnly = true)
public final class McqqImagesForge {
    @Mod.EventHandler
    public void preInit(FMLPreInitializationEvent event) {
        try {
            MediaSource media = new MediaSource(event.getModConfigurationDirectory().toPath().resolve("mcqq-images.properties"));
            if (media.isEnabled()) MinecraftForge.EVENT_BUS.register(new ChatPreviews(media));
        } catch (IOException | RuntimeException failure) {
            event.getModLog().warn("Could not enable QQ image previews", failure);
        }
    }
}
