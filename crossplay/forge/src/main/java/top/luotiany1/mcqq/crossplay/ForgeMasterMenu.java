package top.luotiany1.mcqq.crossplay;

import net.minecraft.client.gui.GuiButton;
import net.minecraft.client.gui.GuiScreen;

final class ForgeMasterMenu extends GuiScreen {
    private static final int COLUMNS = 4;
    private static final int GAP = 4;
    private final int id;
    private final GalMenu menu;
    private boolean replied;

    ForgeMasterMenu(int id, GalMenu menu) {
        this.id = id;
        this.menu = menu;
    }

    @Override
    public void initGui() {
        int buttonWidth = Math.min(140, (width - 16 - (COLUMNS - 1) * GAP) / COLUMNS);
        int left = (width - COLUMNS * buttonWidth - (COLUMNS - 1) * GAP) / 2;
        int top = Math.max(58, (height - 4 * 24) / 2);
        for (int index = 0; index < menu.buttons.size(); index++) {
            String label = fontRenderer.trimStringToWidth(menu.buttons.get(index).label, buttonWidth - 8);
            buttonList.add(new GuiButton(index, left + index % COLUMNS * (buttonWidth + GAP),
                    top + index / COLUMNS * 24, buttonWidth, 20, label));
        }
    }

    @Override
    public void drawScreen(int mouseX, int mouseY, float partialTicks) {
        drawDefaultBackground();
        drawCenteredString(fontRenderer, menu.title, width / 2, 16, 0xFFFFFF);
        drawCenteredString(fontRenderer, fontRenderer.trimStringToWidth(menu.content, width - 16),
                width / 2, 36, 0xC8C8C8);
        super.drawScreen(mouseX, mouseY, partialTicks);
    }

    @Override
    protected void actionPerformed(GuiButton button) {
        reply(button.id);
        mc.displayGuiScreen(null);
    }

    @Override
    public void onGuiClosed() {
        reply(GalMenu.CLOSED);
    }

    @Override
    public boolean doesGuiPauseGame() {
        return false;
    }

    private void reply(int selected) {
        if (!replied) {
            replied = true;
            ForgeMaster.api().sendEvent(mc, "mastergal:menu_result", GalMenu.encodeResult(id, selected));
        }
    }
}
