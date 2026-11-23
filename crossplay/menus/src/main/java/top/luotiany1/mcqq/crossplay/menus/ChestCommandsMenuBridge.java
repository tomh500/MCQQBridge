package top.luotiany1.mcqq.crossplay.menus;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.bukkit.ChatColor;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.inventory.InventoryHolder;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.plugin.java.JavaPlugin;
import top.luotiany1.mcqq.crossplay.GalMenu;
import top.luotiany1.mcqq.crossplay.SpigotMasterGAL;

/** Optional reflective hook: ChestCommands stays a soft dependency and owns its click actions. */
final class ChestCommandsMenuBridge implements Listener {
    private final JavaPlugin plugin;
    private final SpigotMasterGAL masterGal;
    private final Set<java.util.UUID> openingNativeMenu = new HashSet<>();

    ChestCommandsMenuBridge(JavaPlugin plugin, SpigotMasterGAL masterGal) {
        this.plugin = plugin;
        this.masterGal = masterGal;
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onMenuOpen(InventoryOpenEvent event) {
        if (!(event.getPlayer() instanceof Player)) {
            return;
        }
        Player player = (Player) event.getPlayer();
        if (openingNativeMenu.contains(player.getUniqueId())) {
            return;
        }
        Object menuView = getMenuView(event.getInventory().getHolder());
        if (menuView == null) {
            return;
        }
        List<Integer> slots = new ArrayList<>();
        Object menu = invoke(menuView, "getMenu");
        if (menu == null) {
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
        List<Integer> firstPage = page(slots, 0, 14);
        List<GalMenu.Button> buttons = render(player, menuView, firstPage);
        if (slots.size() > 14) {
            buttons.add(new GalMenu.Button("下一页"));
        }
        String title = String.valueOf(invoke(menu, "getTitle"));
        if (masterGal.showMenu(player, new GalMenu(clean(title), "选择菜单项目。", buttons), result -> {
            if (result == GalMenu.UNAVAILABLE) {
                openNative(player, menuView);
            } else if (result >= 0 && result < firstPage.size()) {
                Object icon = invoke(menuView, "getIcon", new Class<?>[]{int.class}, firstPage.get(result));
                invokeIcon(icon, menuView, player);
            } else if (result == 14 && slots.size() > 14) {
                openPage(player, menuView, slots, 14, title);
            }
        })) {
            return;
        }
        event.setCancelled(true);
    }

    private void openPage(Player player, Object menuView, List<Integer> slots, int offset, String title) {
        List<Integer> current = page(slots, offset, 14);
        List<GalMenu.Button> buttons = render(player, menuView, current);
        if (offset > 0) {
            buttons.add(new GalMenu.Button("上一页"));
        }
        if (offset + current.size() < slots.size()) {
            buttons.add(new GalMenu.Button("下一页"));
        }
        masterGal.showMenu(player, new GalMenu(clean(title), "选择菜单项目。", buttons), result -> {
            if (result == GalMenu.UNAVAILABLE) {
                openNative(player, menuView);
            } else if (result >= 0 && result < current.size()) {
                Object icon = invoke(menuView, "getIcon", new Class<?>[]{int.class}, current.get(result));
                invokeIcon(icon, menuView, player);
            } else if (result == current.size() && offset > 0) {
                openPage(player, menuView, slots, Math.max(0, offset - 14), title);
            } else if (result == current.size() + (offset > 0 ? 1 : 0)
                    && offset + current.size() < slots.size()) {
                openPage(player, menuView, slots, offset + 14, title);
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

    private Object getMenuView(InventoryHolder holder) {
        return invoke(holder, "getMenuView");
    }

    private Object invoke(Object target, String name) {
        return invoke(target, name, new Class<?>[0]);
    }

    private Object invoke(Object target, String name, Class<?>[] parameterTypes, Object... arguments) {
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
        return clean.replace('\n', ' ').replace('\r', ' ');
    }
}
