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
        saveDefaultConfig();
        Plugin chestCommands = getServer().getPluginManager().getPlugin("ChestCommands");
        if (chestCommands != null && chestCommands.isEnabled()) {
            try {
                getServer().getPluginManager().registerEvents(
                        new ChestCommandsMenuBridge(this, masterGal, chestCommands), this);
            } catch (ReflectiveOperationException | LinkageError failure) {
                getLogger().warning("ChestCommands menu adapter unavailable; native menus remain enabled.");
            }
        }

        Plugin gadgets = getServer().getPluginManager().getPlugin("GadgetsMenu");
        if (gadgets != null && gadgets.isEnabled() && getConfig().getBoolean("gadgetsmenu-main-form", true)) {
            try {
                getServer().getPluginManager().registerEvents(new GadgetsMenuBridge(gadgets, masterGal), this);
            } catch (ReflectiveOperationException | LinkageError failure) {
                getLogger().warning("GadgetsMenu menu adapter unavailable; native menus remain enabled.");
            }
        }

        Plugin bedWars = getServer().getPluginManager().getPlugin("BedWars1058");
        if (bedWars != null) {
            try {
                Class<?> adapterClass = Class.forName(
                        "top.luotiany1.mcqq.crossplay.menus.BedWarsMenuBridge", true, getClass().getClassLoader());
                Constructor<?> constructor = adapterClass.getConstructor(Plugin.class, SpigotMasterGAL.class,
                        Plugin.class);
                Object adapter = constructor.newInstance(this, masterGal, bedWars);
                adapterClass.getMethod("register").invoke(adapter);
                getLogger().info("BedWars shop adapter registered.");
            } catch (ReflectiveOperationException | LinkageError failure) {
                getLogger().warning("BedWars menu adapter is unavailable; native BedWars shops remain enabled.");
            }
        }
    }
}
