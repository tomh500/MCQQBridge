package top.luotiany1.mcqq.crossplay.menus;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import org.bukkit.ChatColor;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.inventory.ClickType;
import org.bukkit.event.inventory.InventoryAction;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.event.inventory.InventoryType;
import org.bukkit.inventory.Inventory;
import org.bukkit.inventory.InventoryView;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.plugin.Plugin;
import top.luotiany1.mcqq.crossplay.BedrockForm;
import top.luotiany1.mcqq.crossplay.SpigotMasterGAL;

final class GadgetsMenuBridge implements Listener {
    private static final String MAIN_MENU = "com.yapzhenyie.GadgetsMenu.menu.menus.MainMenu";
    private static final int PAGE_SIZE = 13;
    private final Plugin gadgets;
    private final SpigotMasterGAL masterGal;
    private final Object menuListener;
    private final Method click;

    GadgetsMenuBridge(Plugin gadgets, SpigotMasterGAL masterGal) throws ReflectiveOperationException {
        this.gadgets = gadgets;
        this.masterGal = masterGal;
        Class<?> main = Class.forName(MAIN_MENU, true, gadgets.getClass().getClassLoader());
        menuListener = main.getConstructor().newInstance();
        click = main.getMethod("onInvClickMainMenu", InventoryClickEvent.class);
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onOpen(InventoryOpenEvent event) {
        if (!(event.getPlayer() instanceof Player) || !gadgets.isEnabled()
                || event.getInventory().getType() != InventoryType.CHEST) {
            return;
        }
        // GadgetsMenu uses ordinary chest inventories. Only convert its actual main-menu opens.
        boolean fromMainMenu = false;
        for (StackTraceElement call : Thread.currentThread().getStackTrace()) {
            if (MAIN_MENU.equals(call.getClassName()) && "openMainMenu".equals(call.getMethodName())) {
                fromMainMenu = true;
                break;
            }
        }
        if (!fromMainMenu) {
            return;
        }
        List<Integer> slots = new ArrayList<>();
        Inventory inventory = event.getInventory();
        for (int slot = 0; slot < inventory.getSize(); slot++) {
            if (!label(inventory.getItem(slot)).isEmpty()) {
                slots.add(slot);
            }
        }
        Player player = (Player) event.getPlayer();
        if (!slots.isEmpty() && showPage(player, event.getView(), player.getWorld(), slots, 0)) {
            event.setCancelled(true);
        }
    }

    private boolean showPage(Player player, InventoryView view, World world, List<Integer> slots, int offset) {
        List<Integer> page = slots.subList(offset, Math.min(offset + PAGE_SIZE, slots.size()));
        List<BedrockForm.Button> buttons = new ArrayList<>();
        for (int slot : page) {
            buttons.add(new BedrockForm.Button(label(view.getTopInventory().getItem(slot)), ""));
        }
        int previous = offset > 0 ? buttons.size() : -1;
        if (previous >= 0) {
            buttons.add(new BedrockForm.Button("上一页", ""));
        }
        int next = offset + page.size() < slots.size() ? buttons.size() : -1;
        if (next >= 0) {
            buttons.add(new BedrockForm.Button("下一页", ""));
        }
        int nativeMenu = buttons.size();
        buttons.add(new BedrockForm.Button("打开原版菜单", ""));
        String title = ChatColor.stripColor(view.getTitle());
        return masterGal.showBedrockForm(player, new BedrockForm(title, "选择菜单项目。", buttons), result -> {
            if (!player.isOnline() || player.getWorld() != world || !gadgets.isEnabled()) {
                return;
            }
            if (result == BedrockForm.UNAVAILABLE || result == nativeMenu) {
                player.openInventory(view.getTopInventory());
            } else if (result >= 0 && result < page.size()) {
                select(view, page.get(result));
            } else if (result >= 0 && (result == previous || result == next)) {
                int newOffset = result == previous ? offset - PAGE_SIZE : offset + PAGE_SIZE;
                if (!showPage(player, view, world, slots, newOffset)) {
                    player.openInventory(view.getTopInventory());
                }
            }
        });
    }

    private void select(InventoryView view, int slot) {
        InventoryClickEvent event = new InventoryClickEvent(view, InventoryType.SlotType.CONTAINER, slot,
                ClickType.LEFT, InventoryAction.PICKUP_ALL);
        try {
            click.invoke(menuListener, event);
        } catch (ReflectiveOperationException failure) {
            gadgets.getLogger().warning("Could not open the selected GadgetsMenu entry.");
        }
    }

    private static String label(ItemStack item) {
        if (item == null || item.getType() == Material.AIR || !item.hasItemMeta()) {
            return "";
        }
        ItemMeta meta = item.getItemMeta();
        if (!meta.hasDisplayName()) {
            return "";
        }
        return ChatColor.stripColor(meta.getDisplayName()).replaceAll("[\\p{Cntrl}]", " ").trim();
    }
}
