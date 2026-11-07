package top.luotiany1.mcqq;

import java.util.UUID;

/** Source labels, independent from permission-group prefixes. */
public final class ChatFormat {
    private static final java.util.Set<String> GROUP_LABELS = java.util.Collections.newSetFromMap(new java.util.concurrent.ConcurrentHashMap<String,Boolean>());
    public static boolean isQQ(String text) { if(text.startsWith("[群内]")) return true; for(String label: GROUP_LABELS) if(text.startsWith(label)) return true; return false; }
    private ChatFormat() { }
    public static String gamePrefix(String server, boolean bedrock) {
        return gamePrefix(server, bedrock, false);
    }
    public static String gamePrefix(String server, boolean bedrock, boolean said) {
        return (said ? "\u00a7c[" : "\u00a77[") + plain(server) + "]" + (bedrock ? "\u00a7a[bedrock]" : "\u00a76[java]") + "\u00a7r";
    }
    public static String qqPrefix(String role, String title) {
        return qqPrefix(role, title, "群内");
    }
    public static String qqPrefix(String role, String title, String groupName) {
        String group = plain(groupName).trim();
        if (group.isEmpty()) group = "群内";
        if (group.length() > 64) group = group.substring(0, 64);
        GROUP_LABELS.add("[" + group + "]");
        String cleanTitle = plain(title).trim();
        String label = !cleanTitle.isEmpty() ? cleanTitle : "owner".equals(role) ? "群主" : "admin".equals(role) ? "管理员" : "";
        String color = "owner".equals(role) ? "\u00a7e" : "admin".equals(role) ? "\u00a7b" : "\u00a7d";
        return "\u00a77[" + group + "]" + (label.isEmpty() ? "" : color + "[" + label + "]") + "\u00a7r";
    }
    public static String plain(String text) {
        return (text == null ? "" : text).replaceAll("(?i)[\u00a7&][0-9a-fk-orx]", "").replaceAll("[\\p{Cc}\\p{Cf}\\[\\]]", "");
    }
    public static boolean isBedrock(UUID uuid) {
        try {
            Class<?> type = Class.forName("org.geysermc.floodgate.api.FloodgateApi");
            Object api = type.getMethod("getInstance").invoke(null);
            return (Boolean) type.getMethod("isFloodgatePlayer", UUID.class).invoke(api, uuid);
        } catch (ReflectiveOperationException | LinkageError unavailable) {
            return false;
        }
    }
}
