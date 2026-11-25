package top.luotiany1.mcqq.crossplay.menus;

import java.lang.reflect.Method;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.function.BiPredicate;
import java.util.function.IntConsumer;
import java.util.function.Function;
import java.util.function.Predicate;
import org.bukkit.ChatColor;
import org.bukkit.World;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.inventory.InventoryHolder;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.java.JavaPlugin;
import top.luotiany1.mcqq.crossplay.GalMenu;
import top.luotiany1.mcqq.crossplay.SpigotMasterGAL;

/** Optional reflective hook: ChestCommands stays a soft dependency and owns its click actions. */
final class ChestCommandsMenuBridge implements Listener {
    private final JavaPlugin plugin;
    private static final int PAGE_SIZE = 13;
    private final MenuDispatcher dispatcher;
    private final Function<InventoryHolder, Object> menuViewOf;
    private final Predicate<Player> supportsForms;
    private final BiPredicate<Player, Object> allowedMenu;
    private final Set<java.util.UUID> openingNativeMenu = new HashSet<>();

    ChestCommandsMenuBridge(JavaPlugin plugin, SpigotMasterGAL masterGal, Plugin chestCommands)
            throws ReflectiveOperationException {
        this(plugin, masterGal::showBedrockMenu, masterGal::supportsBedrockForms,
                menuPolicy(plugin, chestCommands), ChestCommandsMenuBridge::getMenuView);
    }

    ChestCommandsMenuBridge(JavaPlugin plugin, MenuDispatcher dispatcher, Predicate<Player> supportsForms,
                            BiPredicate<Player, Object> allowedMenu, Function<InventoryHolder, Object> menuViewOf) {
        this.plugin = plugin;
        this.dispatcher = dispatcher;
        this.supportsForms = supportsForms;
        this.allowedMenu = allowedMenu;
        this.menuViewOf = menuViewOf;
    }

    private static BiPredicate<Player, Object> menuPolicy(JavaPlugin plugin, Plugin chestCommands)
            throws ReflectiveOperationException {
        String root = "me.filoghost.chestcommands.";
        ClassLoader loader = chestCommands.getClass().getClassLoader();
        Class<?> menuType = loader.loadClass(root + "menu.InternalMenu");
        Method sourceFile = menuType.getMethod("getSourceFile");
        Method openPermission = menuType.getMethod("getOpenPermission");
        Method activeMenu = loader.loadClass(root + "menu.MenuManager").getMethod("getMenuByFileName", String.class);
        Class<?> holderType = loader.loadClass(root + "inventory.MenuInventoryHolder");
        holderType.getMethod("getMenuView");
        return (player, menu) -> {
            if (!chestCommands.isEnabled() || !menuType.isInstance(menu)) {
                return false;
            }
            try {
                Path source = (Path) sourceFile.invoke(menu);
                String name = source.getFileName().toString();
                return plugin.getConfig().getStringList("chestcommands-form-menus").contains(name)
                        && activeMenu.invoke(null, name) == menu
                        && player.hasPermission((String) openPermission.invoke(menu));
            } catch (ReflectiveOperationException | RuntimeException failure) {
                return false;
            }
        };
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onMenuOpen(InventoryOpenEvent event) {
        if (!(event.getPlayer() instanceof Player)) {
            return;
        }
        Player player = (Player) event.getPlayer();
        if (openingNativeMenu.contains(player.getUniqueId()) || !supportsForms.test(player)) {
            return;
        }
        Object menuView = menuViewOf.apply(event.getInventory().getHolder());
        if (menuView == null) {
            return;
        }
        List<Integer> slots = new ArrayList<>();
        Object menu = invoke(menuView, "getMenu");
        if (menu == null || !allowedMenu.test(player, menu)) {
            return;
        }
        int rows = number(invoke(menu, "getRows"), 0);
        for (int slot = 0; slot < rows * 9; slot++) {
            if (invoke(menuView, "getIcon", new Class<?>[]{int.class}, slot) != null) {
                slots.add(slot);
            }
        }
        if (slots.isEmpty()) {
            return;
        }
        if (showPage(player, player.getWorld(), menuView, menu, slots, 0)) {
            event.setCancelled(true);
        }
    }

    private boolean showPage(Player player, World world, Object menuView, Object menu,
                             List<Integer> slots, int offset) {
        List<Integer> current = page(slots, offset, PAGE_SIZE);
        List<GalMenu.Button> buttons = render(player, menuView, current);
        int previous = offset > 0 ? buttons.size() : -1;
        if (previous >= 0) {
            buttons.add(new GalMenu.Button("上一页"));
        }
        int next = offset + current.size() < slots.size() ? buttons.size() : -1;
        if (next >= 0) {
            buttons.add(new GalMenu.Button("下一页"));
        }
        int nativeMenu = buttons.size();
        buttons.add(new GalMenu.Button("打开原版菜单"));
        String title = clean(String.valueOf(invoke(menu, "getTitle")));
        return dispatcher.showMenu(player, new GalMenu(title, "选择菜单项目。", buttons), result -> {
            if (!player.isOnline() || player.getWorld() != world || !allowedMenu.test(player, menu)) {
                return;
            }
            if (result == GalMenu.UNAVAILABLE || result == nativeMenu) {
                openNative(player, menuView);
            } else if (result >= 0 && result < current.size()) {
                Object icon = invoke(menuView, "getIcon", new Class<?>[]{int.class}, current.get(result));
                invokeIcon(icon, menuView, player);
            } else if (result >= 0 && (result == previous || result == next)) {
                int newOffset = result == previous ? offset - PAGE_SIZE : offset + PAGE_SIZE;
                if (!showPage(player, world, menuView, menu, slots, newOffset)) {
                    openNative(player, menuView);
                }
            }
        });
    }

    private List<GalMenu.Button> render(Player player, Object menuView, List<Integer> slots) {
        List<GalMenu.Button> buttons = new ArrayList<>();
        for (int slot : slots) {
            Object icon = invoke(menuView, "getIcon", new Class<?>[]{int.class}, slot);
            Object rendered = invoke(icon, "render", new Class<?>[]{Player.class}, player);
            String label = "位置 " + (slot + 1);
            if (rendered instanceof ItemStack) {
                ItemStack stack = (ItemStack) rendered;
                ItemMeta meta = stack.getItemMeta();
                label = meta != null && meta.hasDisplayName() ? meta.getDisplayName() : stack.getType().name();
            }
            buttons.add(new GalMenu.Button(clean(label)));
        }
        return buttons;
    }

    private void invokeIcon(Object icon, Object menuView, Player player) {
        if (icon == null) {
            return;
        }
        Method method = findMethod(icon.getClass(), "onClick", 2);
        if (method != null) {
            try {
                method.invoke(icon, menuView, player);
            } catch (ReflectiveOperationException | RuntimeException failure) {
                plugin.getLogger().warning("ChestCommands click failed: " + failure.getClass().getSimpleName());
            }
        }
    }

    private void openNative(Player player, Object menuView) {
        java.util.UUID uuid = player.getUniqueId();
        openingNativeMenu.add(uuid);
        try {
            invoke(menuView, "open");
        } finally {
            openingNativeMenu.remove(uuid);
        }
    }

    private static Object getMenuView(InventoryHolder holder) {
        return holder != null && holder.getClass().getName().equals(
                "me.filoghost.chestcommands.inventory.MenuInventoryHolder") ? invoke(holder, "getMenuView") : null;
    }

    private static Object invoke(Object target, String name) {
        return invoke(target, name, new Class<?>[0]);
    }

    private static Object invoke(Object target, String name, Class<?>[] parameterTypes, Object... arguments) {
        if (target == null) {
            return null;
        }
        try {
            Method method = target.getClass().getMethod(name, parameterTypes);
            return method.invoke(target, arguments);
        } catch (ReflectiveOperationException | RuntimeException ignored) {
            return null;
        }
    }

    private Method findMethod(Class<?> type, String name, int parameterCount) {
        for (Method method : type.getMethods()) {
            if (method.getName().equals(name) && method.getParameterTypes().length == parameterCount) {
                return method;
            }
        }
        return null;
    }

    private int number(Object value, int fallback) {
        return value instanceof Number ? ((Number) value).intValue() : fallback;
    }

    private List<Integer> page(List<Integer> slots, int start, int count) {
        return new ArrayList<>(slots.subList(start, Math.min(slots.size(), start + count)));
    }

    private String clean(String text) {
        String clean = ChatColor.stripColor(ChatColor.translateAlternateColorCodes('&', text == null ? "" : text));
        clean = clean.replace('\n', ' ').replace('\r', ' ');
        return clean.length() <= 128 ? clean : clean.substring(0, 127) + "…";
    }

    @FunctionalInterface
    interface MenuDispatcher {
        boolean showMenu(Player player, GalMenu menu, IntConsumer onResult);
    }
}
