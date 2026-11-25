package top.luotiany1.mcqq.crossplay.menus;

import java.lang.reflect.Proxy;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
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
        new ChestCommandsMenuBridge(null, (player, menu, result) -> {
            throw new AssertionError("Java must bypass form dispatch");
        }, player -> false, (player, menu) -> true, holder -> holder).onMenuOpen(unsupported);
        check(!unsupported.isCancelled(), "Java keeps the native inventory");

        AtomicReference<IntConsumer> firstPageResult = new AtomicReference<>();
        AtomicBoolean allowed = new AtomicBoolean(true);
        ChestCommandsMenuBridge bridge = new ChestCommandsMenuBridge(null, (player, menu, result) ->
                firstPageResult.compareAndSet(null, result), player -> true, (player, menu) -> allowed.get(),
                holder -> holder);
        InventoryOpenEvent supported = openEvent(menuView);
        bridge.onMenuOpen(supported);
        check(supported.isCancelled(), "Dispatching a replacement must cancel the native inventory");
        check(menuView.opens == 0, "Native fallback must wait for an unavailable result");
        firstPageResult.getAndSet(null).accept(GalMenu.UNAVAILABLE);
        check(menuView.opens == 1, "An unavailable replacement must reopen the native inventory");
        bridge.onMenuOpen(openEvent(menuView));
        firstPageResult.getAndSet(null).accept(14);
        check(menuView.opens == 2, "The native menu button must reopen the original view");
        bridge.onMenuOpen(openEvent(menuView));
        firstPageResult.get().accept(13);
        check(menuView.opens == 3, "A failed next-page dispatch must reopen the native inventory");
        firstPageResult.set(null);
        InventoryOpenEvent openedBeforePermissionChange = openEvent(menuView);
        bridge.onMenuOpen(openedBeforePermissionChange);
        allowed.set(false);
        firstPageResult.getAndSet(null).accept(0);
        check(menuView.clicks == 0, "An invalidated menu must ignore a delayed response");
        InventoryOpenEvent unlisted = openEvent(menuView);
        bridge.onMenuOpen(unlisted);
        check(!unlisted.isCancelled(), "A menu without opt-in must stay native");
        allowed.set(true);
        bridge.onMenuOpen(openEvent(menuView));
        firstPageResult.getAndSet(null).accept(0);
        check(menuView.clicks == 1, "A valid selection invokes the original icon");
        bridge.onMenuOpen(openEvent(menuView));
        firstPageResult.getAndSet(null).accept(GalMenu.CLOSED);
        check(menuView.clicks == 1 && menuView.opens == 3, "Closing is cancellation");
    }

    private static InventoryOpenEvent openEvent(MenuView menu) {
        UUID uuid = UUID.randomUUID();
        Player player = (Player) Proxy.newProxyInstance(Player.class.getClassLoader(),
                new Class<?>[]{Player.class}, (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "getUniqueId": return uuid;
                        case "isOnline": return true;
                        case "getWorld": return null;
                        default: throw new AssertionError(method);
                    }
                });
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
        private int clicks;

        public MenuView getMenuView() { return this; }
        public MenuView getMenu() { return this; }
        public int getRows() { return 2; }
        public String getTitle() { return "Test menu"; }
        public Object getIcon(int slot) { return slot < 15 ? new Icon() : null; }
        public final class Icon {
            public void onClick(MenuView view, Player player) { clicks++; }
        }
        public void open() { opens++; }
        @Override public Inventory getInventory() { return null; }
    }
}
