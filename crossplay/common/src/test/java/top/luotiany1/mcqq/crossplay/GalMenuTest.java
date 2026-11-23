package top.luotiany1.mcqq.crossplay;

import java.util.Arrays;

public final class GalMenuTest {
    public static void main(String[] args) {
        GalMenu menu = new GalMenu("起床战争商店", "由服务器验证购买。", Arrays.asList(
                new GalMenu.Button("羊毛", "textures/ui/mastergal/probe.png"),
                new GalMenu.Button("剑"), new GalMenu.Button("返回")));
        GalMenu.Frame opened = GalMenu.decode(menu.encodeOpen(71));
        check(opened != null && opened.id == 71 && opened.menu != null);
        check(opened.menu.buttons.size() == 3 && "羊毛".equals(opened.menu.buttons.get(0).label));
        check("textures/ui/mastergal/probe.png".equals(opened.menu.buttons.get(0).texture));
        GalMenu.Frame selected = GalMenu.decode(GalMenu.encodeResult(71, 1));
        check(selected != null && selected.id == 71 && selected.menu == null && selected.index == 1);
        check(GalMenu.decode(new byte[] {1, 1, 0, 0, 0, 1, 99}) == null);
        expectInvalid(() -> new GalMenu("菜单", "", Arrays.asList()));
        expectInvalid(() -> new GalMenu("菜单", "", Arrays.asList(new GalMenu.Button("坏路径", "../secret.png"))));
        System.out.println("MasterGAL menu open/result codec and bounds passed");
    }

    private static void check(boolean condition) {
        if (!condition) {
            throw new AssertionError("MasterGAL menu test condition failed");
        }
    }

    private static void expectInvalid(Runnable action) {
        try {
            action.run();
            throw new AssertionError("Expected invalid menu to be rejected");
        } catch (IllegalArgumentException expected) {
            // expected
        }
    }
}
