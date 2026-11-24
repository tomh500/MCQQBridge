package top.luotiany1.mcqq.crossplay.menus;

import com.andrei1058.bedwars.api.arena.IArena;
import com.andrei1058.bedwars.api.arena.shop.ICategoryContent;
import com.andrei1058.bedwars.api.events.shop.ShopOpenEvent;
import com.andrei1058.bedwars.shop.ShopCache;
import com.andrei1058.bedwars.shop.ShopManager;
import com.andrei1058.bedwars.shop.main.CategoryContent;
import com.andrei1058.bedwars.shop.main.ShopCategory;
import com.andrei1058.bedwars.shop.quickbuy.PlayerQuickBuyCache;
import com.andrei1058.bedwars.shop.quickbuy.QuickBuyElement;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.bukkit.ChatColor;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.plugin.Plugin;
import top.luotiany1.mcqq.crossplay.GalMenu;
import top.luotiany1.mcqq.crossplay.SpigotMasterGAL;

/** Optional cross-edition front end for BedWars1058's existing, server-owned shop. */
public final class BedWarsMenuBridge implements Listener {
    private final Plugin plugin;
    private final Set<java.util.UUID> openingNativeShop = new HashSet<>();
    private SpigotMasterGAL masterGal;
    private com.andrei1058.bedwars.api.BedWars bedWars;

    public BedWarsMenuBridge(Plugin plugin, SpigotMasterGAL masterGal, Plugin bedWarsPlugin)
            throws ReflectiveOperationException {
        this.plugin = plugin;
        this.masterGal = masterGal;
        try {
            bedWars = (com.andrei1058.bedwars.api.BedWars) bedWarsPlugin.getClass()
                    .getMethod("getAPI").invoke(bedWarsPlugin);
        } catch (ReflectiveOperationException incompatible) {
            throw incompatible;
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onShopOpen(ShopOpenEvent event) {
        if (bedWars == null || openingNativeShop.contains(event.getPlayer().getUniqueId())) {
            return;
        }
        Player player = event.getPlayer();
        if (!eligible(player)) {
            return;
        }
        if (openRoot(player)) {
            event.setCancelled(true);
        }
    }

    private boolean eligible(Player player) {
        IArena arena = bedWars.getArenaUtil().getArenaByPlayer(player);
        return player.isOnline() && arena != null && arena.isPlayer(player) && !arena.isSpectator(player)
                && ShopCache.getShopCache(player.getUniqueId()) != null
                && PlayerQuickBuyCache.getQuickBuyCache(player.getUniqueId()) != null;
    }

    private boolean openRoot(Player player) {
        return openRoot(player, 0);
    }

    private boolean openRoot(Player player, int page) {
        List<GalMenu.Button> buttons = new ArrayList<>();
        List<RunnableAction> actions = new ArrayList<>();
        buttons.add(new GalMenu.Button("快捷购买"));
        actions.add(() -> openQuickBuy(player));
        List<ShopCategory> categories = new ArrayList<>(ShopManager.getShop().getCategoryList());
        int pageCount = pageCount(categories.size(), 12);
        int currentPage = Math.max(0, Math.min(page, pageCount - 1));
        int start = currentPage * 12;
        int end = Math.min(categories.size(), start + 12);
        for (int i = start; i < end; i++) {
            ShopCategory category = categories.get(i);
            buttons.add(new GalMenu.Button(clean(categoryName(category))));
            actions.add(() -> openCategory(player, category));
        }
        if (currentPage > 0) {
            buttons.add(new GalMenu.Button("上一页"));
            actions.add(() -> openRoot(player, currentPage - 1));
        }
        if (currentPage + 1 < pageCount) {
            buttons.add(new GalMenu.Button("下一页"));
            actions.add(() -> openRoot(player, currentPage + 1));
        }
        buttons.add(new GalMenu.Button("打开原版商店"));
        actions.add(() -> openNativeShop(player));
        return present(player, "起床战争商店", "商品和购买条件由 BedWars1058 在服务器上实时处理。", buttons, actions);
    }

    private void openQuickBuy(Player player) {
        openQuickBuy(player, 0);
    }

    private void openQuickBuy(Player player, int page) {
        PlayerQuickBuyCache quickBuy = PlayerQuickBuyCache.getQuickBuyCache(player.getUniqueId());
        List<QuickBuyElement> elements = quickBuy.getElements().stream()
                .filter(QuickBuyElement::isLoaded).filter(element -> element.getCategoryContent() != null)
                .collect(Collectors.toList());
        List<GalMenu.Button> buttons = new ArrayList<>();
        List<RunnableAction> actions = new ArrayList<>();
        int pageCount = pageCount(elements.size(), 13);
        int currentPage = Math.max(0, Math.min(page, pageCount - 1));
        int start = currentPage * 13;
        int end = Math.min(elements.size(), start + 13);
        for (int i = start; i < end; i++) {
            QuickBuyElement element = elements.get(i);
            CategoryContent item = element.getCategoryContent();
            buttons.add(new GalMenu.Button(itemName(item, player)));
            actions.add(() -> buy(player, item));
        }
        addProductNavigation(player, buttons, actions, currentPage, pageCount, true, null);
        buttons.add(new GalMenu.Button("返回分类"));
        actions.add(() -> openRoot(player));
        List<CategoryContent> contents = elements.stream().map(QuickBuyElement::getCategoryContent)
                .collect(Collectors.toList());
        present(player, "快捷购买", "选择一个已配置的快捷购买项目。" + currentCostText(player, contents), buttons, actions);
    }

    private void openCategory(Player player, ShopCategory category) {
        openCategory(player, category, 0);
    }

    private void openCategory(Player player, ShopCategory category, int page) {
        ShopCache cache = ShopCache.getShopCache(player.getUniqueId());
        if (!eligible(player) || cache == null || !isCurrentCategory(category)) {
            return;
        }
        List<GalMenu.Button> buttons = new ArrayList<>();
        List<RunnableAction> actions = new ArrayList<>();
        List<CategoryContent> availableItems = new ArrayList<>();
        for (CategoryContent item : category.getCategoryContentList()) {
            ItemStack display = item.getItemStack(player, cache);
            if (display == null || display.getType().name().equals("AIR")) {
                continue;
            }
            availableItems.add(item);
        }
        int pageCount = pageCount(availableItems.size(), 13);
        int currentPage = Math.max(0, Math.min(page, pageCount - 1));
        int start = currentPage * 13;
        int end = Math.min(availableItems.size(), start + 13);
        for (int i = start; i < end; i++) {
            CategoryContent item = availableItems.get(i);
            buttons.add(new GalMenu.Button(itemName(item, player)));
            actions.add(() -> buy(player, item));
        }
        addProductNavigation(player, buttons, actions, currentPage, pageCount, false, category);
        buttons.add(new GalMenu.Button("返回分类"));
        actions.add(() -> openRoot(player));
        present(player, clean(categoryName(category)), "选择商品。" + currentCostText(player, category.getCategoryContentList()),
                buttons, actions);
    }

    private void addProductNavigation(Player player, List<GalMenu.Button> buttons,
                                      List<RunnableAction> actions, int currentPage, int pageCount,
                                      boolean quickBuy, ShopCategory category) {
        if (currentPage > 0) {
            buttons.add(new GalMenu.Button("上一页"));
            actions.add(quickBuy ? () -> openQuickBuy(player, currentPage - 1)
                    : () -> openCategory(player, category, currentPage - 1));
        }
        if (currentPage + 1 < pageCount) {
            buttons.add(new GalMenu.Button("下一页"));
            actions.add(quickBuy ? () -> openQuickBuy(player, currentPage + 1)
                    : () -> openCategory(player, category, currentPage + 1));
        }
    }

    private int pageCount(int size, int pageSize) {
        return Math.max(1, (size + pageSize - 1) / pageSize);
    }

    private boolean present(Player player, String title, String content, List<GalMenu.Button> buttons,
                            List<RunnableAction> actions) {
        if (buttons.isEmpty()) {
            buttons.add(new GalMenu.Button("返回"));
            actions.add(() -> openRoot(player));
        }
        GalMenu menu = new GalMenu(title, truncate(content, 1900), buttons);
        return masterGal.showMenu(player, menu, result -> {
            if (result == GalMenu.UNAVAILABLE) {
                openNativeShop(player);
            } else if (result >= 0 && result < actions.size() && eligible(player)) {
                actions.get(result).run();
            }
        });
    }

    private void buy(Player player, CategoryContent selected) {
        if (!eligible(player) || selected == null || !isCurrentContent(selected)) {
            openNativeShop(player);
            return;
        }
        ShopCache cache = ShopCache.getShopCache(player.getUniqueId());
        if (cache == null) {
            openNativeShop(player);
            return;
        }
        // BedWars1058's own click handler performs affordability, upgrade, event, deduction,
        // inventory, and team-state checks in this method.
        selected.execute(player, cache, selected.getSlot());
        plugin.getServer().getScheduler().runTask(plugin, () -> {
            if (eligible(player)) {
                openQuickBuy(player);
            }
        });
    }

    private void openNativeShop(Player player) {
        if (eligible(player)) {
            java.util.UUID uuid = player.getUniqueId();
            openingNativeShop.add(uuid);
            try {
                ShopManager.getShop().open(player,
                        PlayerQuickBuyCache.getQuickBuyCache(uuid), true);
            } finally {
                openingNativeShop.remove(uuid);
            }
        }
    }

    private boolean isCurrentCategory(ShopCategory candidate) {
        return ShopManager.getShop().getCategoryList().contains(candidate);
    }

    private boolean isCurrentContent(CategoryContent candidate) {
        for (ShopCategory category : ShopManager.getShop().getCategoryList()) {
            if (category.getCategoryContentList().contains(candidate)) {
                return true;
            }
        }
        return false;
    }

    private String itemName(ICategoryContent item, Player player) {
        ItemStack stack = item.getItemStack(player);
        if (stack == null) {
            return item.getIdentifier();
        }
        ItemMeta meta = stack.getItemMeta();
        String name = meta != null && meta.hasDisplayName() ? meta.getDisplayName() : stack.getType().name();
        return clean(name);
    }

    private String currentCostText(Player player, List<? extends ICategoryContent> items) {
        StringBuilder text = new StringBuilder();
        ShopCache cache = ShopCache.getShopCache(player.getUniqueId());
        for (ICategoryContent item : items) {
            if (text.length() >= 1400) {
                text.append("\n…");
                break;
            }
            ItemStack display = item instanceof CategoryContent && cache != null
                    ? ((CategoryContent) item).getItemStack(player, cache) : item.getItemStack(player);
            if (display == null || display.getItemMeta() == null || !display.getItemMeta().hasLore()) {
                continue;
            }
            List<String> lore = display.getItemMeta().getLore();
            text.append("\n").append(itemName(item, player)).append(": ");
            for (String line : lore) {
                String cleaned = clean(line);
                if (!cleaned.isEmpty()) {
                    text.append(cleaned).append(" ");
                }
            }
        }
        return text.toString();
    }

    private String categoryName(ShopCategory category) {
        return category.getName();
    }

    private String clean(String text) {
        return ChatColor.stripColor(text == null ? "" : ChatColor.translateAlternateColorCodes('&', text))
                .replace('\n', ' ').replace('\r', ' ');
    }

    private String truncate(String text, int limit) {
        return text.length() <= limit ? text : text.substring(0, limit - 1) + "…";
    }

    private interface RunnableAction {
        void run();
    }
}
