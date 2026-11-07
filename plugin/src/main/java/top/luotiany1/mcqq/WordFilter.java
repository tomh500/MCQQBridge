package top.luotiany1.mcqq;

import com.google.gson.*;
import net.md_5.bungee.api.chat.TextComponent;
import net.md_5.bungee.api.connection.ProxiedPlayer;
import net.md_5.bungee.api.event.ChatEvent;
import net.md_5.bungee.api.plugin.Listener;
import net.md_5.bungee.event.EventHandler;
import net.md_5.bungee.event.EventPriority;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.*;

/** Netease X19/G79 rules, evaluated before BungeeChat and the QQ bridge. */
public final class WordFilter implements Listener {
    private static final String PREFIX = "level=0_channel=item_comment_content=";
    private static final int BUDGET = 4000000;
    private volatile Rules rules;
    private final MCQQBridge plugin;
    static final class Rules {
        final List<Pattern> red = new ArrayList<>(), yellow = new ArrayList<>();
    }
    static final class BudgetExceeded extends RuntimeException { }
    static final class LimitedText implements CharSequence {
        final String text; final int start, end; final int[] budget;
        LimitedText(String text, int start, int end, int[] budget) { this.text=text; this.start=start; this.end=end; this.budget=budget; }
        public int length() { return end-start; }
        public char charAt(int i) { if (--budget[0] < 0) throw new BudgetExceeded(); if (i < 0 || start+i >= end) throw new IndexOutOfBoundsException(); return text.charAt(start+i); }
        public CharSequence subSequence(int a, int b) { return new LimitedText(text,start+a,start+b,budget); }
        public String toString() { return text.substring(start,end); }
    }
    WordFilter(MCQQBridge plugin) { this.plugin=plugin; reload(); plugin.getProxy().getPluginManager().registerListener(plugin,this); }
    synchronized void reload() {
        if(plugin.chatConfig()!=null && !plugin.chatConfig().getBoolean("word-filter.enabled", true)) { rules=new Rules(); return; }
        try {
            Rules next = new Rules();
            if (plugin.chatConfig() != null) {
                for(String expression: plugin.chatConfig().getStringList("word-filter.red")) next.red.add(Pattern.compile(expression));
                for(String expression: plugin.chatConfig().getStringList("word-filter.yellow")) next.yellow.add(Pattern.compile(expression));
            }
            JsonObject g79 = readRules("G79SensitiveWords.json"), x19 = readRules("X19SensitiveWords.json");
            Set<String> elevated = new HashSet<>();
            for (Map.Entry<String,JsonElement> e : g79.getAsJsonObject("shield").entrySet()) {
                int id = Integer.parseInt(e.getKey());
                if (id >= 1 && id <= 449) elevated.add(e.getValue().getAsString());
            }
            for (JsonObject data : new JsonObject[]{g79, x19}) {
                compile(data, "intercept", next.red);
                for (Map.Entry<String,JsonElement> e : data.getAsJsonObject("shield").entrySet()) {
                    String expression = e.getValue().getAsString();
                    (elevated.contains(expression) ? next.red : next.yellow).add(Pattern.compile(expression));
                }
                compile(data, "replace", next.yellow);
            }
            if (next.red.isEmpty() || next.yellow.isEmpty()) throw new IllegalArgumentException("empty rule category");
            rules=next;
            plugin.getLogger().info("Loaded Netease chat rules: " + next.red.size() + " red, " + next.yellow.size() + " yellow.");
        } catch (Exception e) { rules=null; plugin.getLogger().severe("Word filter unavailable; player chat blocked: " + e); }
    }
    private JsonObject readRules(String file) throws IOException {
        File target = new File(plugin.getDataFolder(), file);
        if(!target.exists()) try(InputStream in=plugin.getResourceAsStream(file)) { java.nio.file.Files.copy(in,target.toPath()); }
        try (Reader in = new InputStreamReader(new FileInputStream(target), StandardCharsets.UTF_8)) {
            return new JsonParser().parse(in).getAsJsonObject().getAsJsonObject("regex");
        }
    }
    private static void compile(JsonObject json, String key, List<Pattern> out) {
        for (Map.Entry<String,JsonElement> entry : json.getAsJsonObject(key).entrySet()) out.add(Pattern.compile(entry.getValue().getAsString()));
    }
    static String apply(Rules rules, String text) {
        String input = PREFIX + text; int[] budget={BUDGET};
        CharSequence limited = new LimitedText(input, 0, input.length(), budget);
        for (Pattern p : rules.red) if (p.matcher(limited).find()) return null;
        boolean[] mask = new boolean[input.length()];
        for (Pattern p : rules.yellow) {
            Matcher m = p.matcher(limited);
            while (m.find()) {
                if (m.start() < PREFIX.length() && m.end() > 0) Arrays.fill(mask, PREFIX.length(), input.length(), true);
                else Arrays.fill(mask, Math.max(PREFIX.length(),m.start()), m.end(), true);
            }
        }
        StringBuilder out = new StringBuilder();
        for (int i=PREFIX.length(); i<input.length();) {
            int cp=input.codePointAt(i), n=Character.charCount(cp);
            if (mask[i] || (n==2 && mask[i+1])) out.append('*'); else out.appendCodePoint(cp);
            i+=n;
        }
        return out.toString();
    }
    String filter(ProxiedPlayer player, String text) {
        if(plugin.chatConfig()!=null && !plugin.chatConfig().getBoolean("word-filter.enabled", true)) return text;
        Rules current=rules;
        if (current == null) { player.sendMessage(new TextComponent("聊天过滤器不可用，请稍后重试。")); return null; }
        try {
            String result=apply(current,text);
            if (result == null) player.disconnect(new TextComponent("聊天包含禁止发送的内容。"));
            return result;
        } catch (BudgetExceeded | StackOverflowError e) {
            player.sendMessage(new TextComponent("聊天内容无法安全检查，请修改后重试。")); return null;
        }
    }
    @EventHandler(priority=EventPriority.LOWEST) public void onChat(ChatEvent event) {
        if (event.isCancelled() || event.isCommand() || !(event.getSender() instanceof ProxiedPlayer)) return;
        String result=filter((ProxiedPlayer)event.getSender(),event.getMessage());
        if (result==null) event.setCancelled(true); else event.setMessage(result);
    }
}



