package top.luotiany1.mcqq.crossplay.menus;

import java.lang.reflect.Constructor;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.java.JavaPlugin;
import top.luotiany1.mcqq.crossplay.SpigotMasterGAL;

/** Main entry point; the BedWars API adapter is only loaded when BedWars is installed. */
public final class MasterGALMenusPlugin extends JavaPlugin {
    @Override
    public void onEnable() {
        Plugin masterGalPlugin = getServer().getPluginManager().getPlugin("SpigotMasterGAL");
        if (!(masterGalPlugin instanceof SpigotMasterGAL)) {
            getLogger().warning("SpigotMasterGAL is required; disabling the optional menu adapter.");
            getServer().getPluginManager().disablePlugin(this);
            return;
        }
        SpigotMasterGAL masterGal = (SpigotMasterGAL) masterGalPlugin;
        getServer().getPluginManager().registerEvents(new ChestCommandsMenuBridge(this, masterGal), this);

        Plugin bedWars = getServer().getPluginManager().getPlugin("BedWars1058");
        if (bedWars != null) {
            try {
                Class<?> adapterClass = Class.forName(
                        "top.luotiany1.mcqq.crossplay.menus.BedWarsMenuBridge", true, getClass().getClassLoader());
                Constructor<?> constructor = adapterClass.getConstructor(Plugin.class, SpigotMasterGAL.class,
                        Plugin.class);
                Object adapter = constructor.newInstance(this, masterGal, bedWars);
                getServer().getPluginManager().registerEvents((org.bukkit.event.Listener) adapter, this);
            } catch (ReflectiveOperationException | LinkageError failure) {
                getLogger().warning("BedWars menu adapter is unavailable; native BedWars shops remain enabled.");
            }
        }
    }
}
