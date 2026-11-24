package top.luotiany1.mcqq;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import net.md_5.bungee.api.chat.BaseComponent;
import net.md_5.bungee.chat.ComponentSerializer;
import org.bukkit.Bukkit;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.AsyncPlayerChatEvent;
import org.bukkit.plugin.Plugin;

final class BedWarsLobbyChat implements Listener {
    private static final String CHANNEL = "mcqq:bwlobby";
    private final SaidPlugin bridge;
    private final Plugin bedWars;
    private final Method arenaLookup;

    BedWarsLobbyChat(SaidPlugin bridge) {
        this.bridge = bridge;
        bedWars = Bukkit.getPluginManager().getPlugin("BedWars1058");
        Method lookup = null;
        if (bedWars != null && bedWars.isEnabled()) {
            try {
                lookup = Class.forName("com.andrei1058.bedwars.arena.Arena", false,
                    bedWars.getClass().getClassLoader()).getMethod("getArenaByPlayer", Player.class);
            } catch (ReflectiveOperationException | LinkageError ex) {
                bridge.getLogger().warning("Could not load the BedWars arena lookup: " + ex.getClass().getSimpleName());
            }
        }
        arenaLookup = lookup;
        if (arenaLookup == null) {
            bridge.getLogger().warning("BedWars lobby chat unavailable; arena isolation remains active.");
            return;
        }
        Bukkit.getMessenger().registerOutgoingPluginChannel(bridge, CHANNEL);
        Bukkit.getMessenger().registerIncomingPluginChannel(bridge, CHANNEL, (channel, carrier, bytes) -> {
            BaseComponent[] message = ComponentSerializer.parse(new String(bytes, StandardCharsets.UTF_8));
            for (Player player : Bukkit.getOnlinePlayers()) {
                if (isInLobby(player)) player.spigot().sendMessage(message);
            }
        });
        Bukkit.getPluginManager().registerEvents(this, bridge);
        bridge.getLogger().info("BedWars lobby chat enabled.");
    }

    boolean isInLobby(Player player) {
        if (arenaLookup == null || !bedWars.isEnabled()) return false;
        try {
            return arenaLookup.invoke(null, player) == null;
        } catch (ReflectiveOperationException ex) {
            return false;
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void relayLobbyChat(AsyncPlayerChatEvent event) {
        // /said fires its own synchronous moderation event. Relay only real player chat here.
        if (!event.isAsynchronous() || !isInLobby(event.getPlayer())) return;
        Player player = event.getPlayer();
        String text = event.getMessage();
        if (text.trim().isEmpty() || text.length() > 2000) return;
        Bukkit.getScheduler().runTask(bridge, () -> {
            if (player.isOnline() && isInLobby(player)) bridge.sendChat(player, text, "", CHANNEL);
        });
    }
}
