package top.luotiany1.mcqq.images.forge112;

import java.lang.reflect.Field;
import java.net.URI;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.ChatLine;
import net.minecraft.client.gui.Gui;
import net.minecraft.client.gui.GuiChat;
import net.minecraft.client.gui.GuiNewChat;
import net.minecraft.client.gui.ScaledResolution;
import net.minecraft.client.multiplayer.WorldClient;
import net.minecraft.client.renderer.GlStateManager;
import net.minecraft.entity.player.EntityPlayer;
import net.minecraft.util.text.ChatType;
import net.minecraft.util.text.ITextComponent;
import net.minecraft.util.text.Style;
import net.minecraft.util.text.TextComponentString;
import net.minecraft.util.text.event.ClickEvent;
import net.minecraftforge.client.event.ClientChatReceivedEvent;
import net.minecraftforge.client.event.GuiScreenEvent;
import net.minecraftforge.client.event.RenderGameOverlayEvent;
import net.minecraftforge.fml.relauncher.ReflectionHelper;
import net.minecraftforge.fml.common.eventhandler.EventPriority;
import net.minecraftforge.fml.common.eventhandler.SubscribeEvent;
import net.minecraftforge.fml.common.gameevent.TickEvent;
import org.lwjgl.input.Keyboard;
import org.lwjgl.input.Mouse;
import org.lwjgl.opengl.GL11;

final class ChatPreviews extends Gui {
    private static final int ROWS = 5;
    private static final int ROW_HEIGHT = 9;
    private static final int MAX_ATTACHMENTS = 8;
    private static final int MAX_MARKERS = 100 * MAX_ATTACHMENTS;
    private final Minecraft client = Minecraft.getMinecraft();
    private final MediaSource media;
    private final PreviewCache cache;
    private final Field drawnLines = ReflectionHelper.findField(GuiNewChat.class, "drawnChatLines", "field_146253_i");
    private final Field scrollPosition = ReflectionHelper.findField(GuiNewChat.class, "scrollPos", "field_146250_j");
    private final String markerPrefix = UUID.randomUUID() + "/";
    private final Map<String, URI> markers = new LinkedHashMap<>();
    private final List<Hit> hits = new ArrayList<>();
    private WorldClient world;
    private long nextMarker;
    private int originX;
    private int originY;
    private URI enlarged;

    ChatPreviews(MediaSource media) {
        this.media = media;
        this.cache = new PreviewCache(client, media);
    }

    @SubscribeEvent(priority = EventPriority.LOWEST)
    public void receiveChat(ClientChatReceivedEvent event) {
        if (!client.isCallingFromMinecraftThread() || event.getType() == ChatType.GAME_INFO) return;
        resetWorld();
        if (!canPreview()) return;

        List<URI> links = new ArrayList<>();
        for (ITextComponent part : event.getMessage()) {
            if (links.size() == MAX_ATTACHMENTS) break;
            String label = part.getUnformattedComponentText().trim();
            if (!"[图片]".equals(label) && !"[表情包]".equals(label)) continue;
            ClickEvent click = part.getStyle().getClickEvent();
            if (click == null || click.getAction() != ClickEvent.Action.OPEN_URL) continue;
            URI link = media.trustedLink(click.getValue());
            if (link != null) links.add(link);
        }
        if (links.isEmpty()) return;

        // Keep the original styles and click actions intact. Only synthetic rows carry private markers.
        ITextComponent message = new TextComponentString("").appendSibling(event.getMessage().createCopy());
        for (URI link : links) {
            while (markers.size() >= MAX_MARKERS) markers.remove(markers.keySet().iterator().next());
            String id = markerPrefix + nextMarker++ + "/";
            markers.put(id, link);
            for (int row = 0; row < ROWS; row++) {
                message.appendSibling(new TextComponentString("\n"));
                message.appendSibling(new TextComponentString("\u00a0").setStyle(new Style().setInsertion(id + row)));
            }
        }
        event.setMessage(message);
    }

    @SubscribeEvent
    public void tick(TickEvent.ClientTickEvent event) {
        if (event.phase != TickEvent.Phase.END) return;
        resetWorld();
        if (!(client.currentScreen instanceof GuiChat) || !canPreview()) {
            enlarged = null;
            hits.clear();
        }
        if (!client.gameSettings.chatLinks) cache.clear();
    }

    private boolean canPreview() {
        return world != null && client.gameSettings.chatLinks
            && client.gameSettings.chatVisibility != EntityPlayer.EnumChatVisibility.HIDDEN;
    }

    private void resetWorld() {
        if (world == client.world) return;
        world = client.world;
        enlarged = null;
        hits.clear();
        markers.clear();
        cache.clear();
    }

    @SubscribeEvent(priority = EventPriority.LOWEST)
    public void captureChatOrigin(RenderGameOverlayEvent.Chat event) {
        originX = event.getPosX() + 2;
        originY = event.getPosY() + 8;
    }

    @SubscribeEvent
    public void drawChat(RenderGameOverlayEvent.Post event) throws IllegalAccessException {
        if (event.getType() != RenderGameOverlayEvent.ElementType.CHAT) return;
        hits.clear();
        if (!canPreview() || client.gameSettings.hideGUI || markers.isEmpty()) return;

        GuiNewChat chat = client.ingameGUI.getChatGUI();
        final boolean open = chat.getChatOpen();
        final float scale = chat.getChatScale();
        final int width = (int) Math.ceil(chat.getChatWidth() / scale);
        final int scroll = scrollPosition.getInt(chat);
        final int visibleCount = chat.getLineCount();
        final int updateCounter = client.ingameGUI.getUpdateCounter();
        @SuppressWarnings("unchecked")
        List<ChatLine> lines = (List<ChatLine>) drawnLines.get(chat);
        Map<String, ImageBlock> blocks = new LinkedHashMap<>();
        for (int visible = 0; visible < visibleCount && visible + scroll < lines.size(); visible++) {
            ChatLine line = lines.get(visible + scroll);
            int age = updateCounter - line.getUpdatedCounter();
            if (!open && age >= 200) continue;
            for (ITextComponent part : line.getChatComponent()) {
                String marker = part.getStyle().getInsertion();
                if (marker == null || !marker.startsWith(markerPrefix)) continue;
                String id = marker.substring(0, marker.length() - 1);
                URI uri = markers.get(id);
                if (uri != null && !blocks.containsKey(id)) {
                    int row = marker.charAt(marker.length() - 1) - '0';
                    if (row >= 0 && row < ROWS) blocks.put(id, new ImageBlock(uri, visible - (ROWS - 1 - row), age));
                }
            }
        }
        if (blocks.isEmpty()) return;

        // GuiNewChat translates by (2, 8) and draws row zero directly above its origin.
        GL11.glPushAttrib(GL11.GL_SCISSOR_BIT);
        ScaledResolution resolution = event.getResolution();
        int factor = resolution.getScaleFactor();
        int left = Math.max(0, originX * factor);
        int bottom = Math.max(0, client.displayHeight - originY * factor);
        int top = Math.min(client.displayHeight, bottom + (int) Math.ceil(visibleCount * ROW_HEIGHT * scale * factor));
        int right = Math.min(client.displayWidth, left + (int) Math.ceil(width * scale * factor));
        GL11.glEnable(GL11.GL_SCISSOR_TEST);
        GL11.glScissor(left, bottom, Math.max(0, right - left), Math.max(0, top - bottom));

        GlStateManager.pushMatrix();
        GlStateManager.translate((float) originX, (float) originY, 0.0F);
        GlStateManager.scale(scale, scale, 1.0F);
        Set<URI> visibleImages = new HashSet<>();
        for (ImageBlock block : blocks.values()) visibleImages.add(block.uri);
        try {
            for (ImageBlock block : blocks.values()) {
                PreviewCache.Preview preview = cache.request(block.uri, visibleImages);
                int y = -(block.bottomRow + ROWS) * ROW_HEIGHT + 2;
                float fade = Math.max(0, Math.min(1, (1 - block.age / 200.0F) * 10));
                float alpha = (open ? 1 : fade * fade) * (client.gameSettings.chatOpacity * 0.9F + 0.1F);
                if (preview == null || !preview.ready() || alpha < 0.02F) continue;
                double ratio = Math.min(Math.min(110, width) / (double) preview.width(), (ROWS * ROW_HEIGHT - 4) / (double) preview.height());
                int imageWidth = Math.max(1, (int) (preview.width() * ratio));
                int imageHeight = Math.max(1, (int) (preview.height() * ratio));
                drawPreview(preview, 0, y, imageWidth, imageHeight, alpha);
                int hitTop = (int) Math.floor(originY + Math.max(y, -visibleCount * ROW_HEIGHT) * scale);
                int hitBottom = (int) Math.ceil(originY + Math.min(0, y + imageHeight) * scale);
                if (open && hitTop < hitBottom) {
                    hits.add(new Hit(block.uri, originX, hitTop, originX + (int) Math.ceil(imageWidth * scale), hitBottom));
                }
            }
        } finally {
            GlStateManager.popMatrix();
            GL11.glPopAttrib();
        }
    }

    private void drawPreview(PreviewCache.Preview preview, int x, int y, int width, int height, float alpha) {
        preview.bind();
        GlStateManager.enableBlend();
        GlStateManager.tryBlendFuncSeparate(770, 771, 1, 0);
        GlStateManager.color(1, 1, 1, alpha);
        try {
            Gui.drawScaledCustomSizeModalRect(x, y, 0, 0, preview.width(), preview.height(),
                width, height, preview.width(), preview.height());
        } finally {
            GlStateManager.color(1, 1, 1, 1);
            GlStateManager.disableBlend();
        }
    }

    @SubscribeEvent
    public void click(GuiScreenEvent.MouseInputEvent.Pre event) {
        if (!(event.getGui() instanceof GuiChat) || !canPreview()) return;
        if (enlarged != null) {
            if (Mouse.getEventButton() == 0 && Mouse.getEventButtonState()) enlarged = null;
            event.setCanceled(true);
            return;
        }
        if (Mouse.getEventButton() != 0 || !Mouse.getEventButtonState()) return;
        int x = Mouse.getEventX() * event.getGui().width / client.displayWidth;
        int y = event.getGui().height - Mouse.getEventY() * event.getGui().height / client.displayHeight - 1;
        for (Hit hit : hits) {
            if (x >= hit.left && x < hit.right && y >= hit.top && y < hit.bottom) {
                enlarged = hit.uri;
                event.setCanceled(true);
                return;
            }
        }
    }

    @SubscribeEvent
    public void key(GuiScreenEvent.KeyboardInputEvent.Pre event) {
        if (enlarged == null || !(event.getGui() instanceof GuiChat)) return;
        if (Keyboard.getEventKey() == Keyboard.KEY_ESCAPE && Keyboard.getEventKeyState()) enlarged = null;
        event.setCanceled(true);
    }

    @SubscribeEvent
    public void drawViewer(GuiScreenEvent.DrawScreenEvent.Post event) {
        if (enlarged == null || !(event.getGui() instanceof GuiChat) || !canPreview()) return;
        PreviewCache.Preview preview = cache.get(enlarged);
        if (preview == null || !preview.ready()) {
            enlarged = null;
            return;
        }
        int width = event.getGui().width;
        int height = event.getGui().height;
        double scale = Math.min(Math.max(1, width - 24) / (double) preview.width(),
            Math.max(1, height - 32) / (double) preview.height());
        int w = Math.max(1, (int) (preview.width() * scale));
        int h = Math.max(1, (int) (preview.height() * scale));
        drawRect(0, 0, width, height, 0xCC000000);
        drawPreview(preview, (width - w) / 2, (height - h) / 2, w, h, 1);
    }

    private static final class ImageBlock {
        final URI uri;
        final int bottomRow;
        final int age;

        ImageBlock(URI uri, int bottomRow, int age) {
            this.uri = uri;
            this.bottomRow = bottomRow;
            this.age = age;
        }
    }

    private static final class Hit {
        final URI uri;
        final int left;
        final int top;
        final int right;
        final int bottom;

        Hit(URI uri, int left, int top, int right, int bottom) {
            this.uri = uri;
            this.left = left;
            this.top = top;
            this.right = right;
            this.bottom = bottom;
        }
    }
}
