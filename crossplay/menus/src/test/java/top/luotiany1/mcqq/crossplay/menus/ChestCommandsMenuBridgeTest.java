package top.luotiany1.mcqq.crossplay.menus;

import java.lang.reflect.Proxy;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.IntConsumer;
import org.bukkit.entity.HumanEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.event.inventory.InventoryType;
import org.bukkit.inventory.Inventory;
import org.bukkit.inventory.InventoryHolder;
import org.bukkit.inventory.InventoryView;
import top.luotiany1.mcqq.crossplay.GalMenu;

public final class ChestCommandsMenuBridgeTest {
    public static void main(String[] args) {
        MenuView menuView = new MenuView();
        InventoryOpenEvent unsupported = openEvent(menuView);
        new ChestCommandsMenuBridge(null, (player, menu, result) -> false).onMenuOpen(unsupported);
        check(!unsupported.isCancelled(), "Unsupported clients must keep the native inventory");

        AtomicReference<IntConsumer> firstPageResult = new AtomicReference<>();
        ChestCommandsMenuBridge bridge = new ChestCommandsMenuBridge(null, (player, menu, result) ->
                firstPageResult.compareAndSet(null, result));
        InventoryOpenEvent supported = openEvent(menuView);
        bridge.onMenuOpen(supported);
        check(supported.isCancelled(), "Dispatching a replacement must cancel the native inventory");
        check(menuView.opens == 0, "Native fallback must wait for an unavailable result");
        firstPageResult.getAndSet(null).accept(GalMenu.UNAVAILABLE);
        check(menuView.opens == 1, "An unavailable replacement must reopen the native inventory");
        bridge.onMenuOpen(openEvent(menuView));
        firstPageResult.get().accept(14);
        check(menuView.opens == 2, "A failed next-page dispatch must reopen the native inventory");
    }

    private static InventoryOpenEvent openEvent(MenuView menu) {
        UUID uuid = UUID.randomUUID();
        Player player = (Player) Proxy.newProxyInstance(Player.class.getClassLoader(),
                new Class<?>[]{Player.class}, (proxy, method, args) -> uuid);
        Inventory inventory = (Inventory) Proxy.newProxyInstance(Inventory.class.getClassLoader(),
                new Class<?>[]{Inventory.class}, (proxy, method, args) -> menu);
        return new InventoryOpenEvent(new InventoryView() {
            @Override public Inventory getTopInventory() { return inventory; }
            @Override public Inventory getBottomInventory() { return null; }
            @Override public HumanEntity getPlayer() { return player; }
            @Override public InventoryType getType() { return InventoryType.CHEST; }
        });
    }

    private static void check(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }

    public static final class MenuView implements InventoryHolder {
        private int opens;

        public MenuView getMenuView() { return this; }
        public MenuView getMenu() { return this; }
        public int getRows() { return 2; }
        public String getTitle() { return "Test menu"; }
        public Object getIcon(int slot) { return slot < 15 ? new Object() : null; }
        public void open() { opens++; }
        @Override public Inventory getInventory() { return null; }
    }
}
