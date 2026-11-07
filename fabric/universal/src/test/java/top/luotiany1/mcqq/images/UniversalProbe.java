package top.luotiany1.mcqq.images;
import java.net.URI;
public final class UniversalProbe {
    private static void check(boolean value) { if(!value)throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        check(UniversalImages.allowed(URI.create("https://gchat.qpic.cn/image.jpg")));
        check(!UniversalImages.allowed(URI.create("http://example.com:18766/mcqq-media/0123456789abcdef0123456789abcdef.gif")));
        for(String url:new String[]{"https://qpic.cn.attacker.invalid/a","http://127.0.0.1/a","file:///tmp/a","https://u:p@qpic.cn/a","https://qpic.cn:8080/a","http://example.com:18766/v1/status"})
            check(!UniversalImages.allowed(URI.create(url)));
        check(Bridge.compatible(new Class<?>[]{int.class,String.class},new Object[]{1,"x"}));
        check(!Bridge.compatible(new Class<?>[]{int.class,String.class},new Object[]{1f,"x"}));
        check(!Bridge.compatible(new Class<?>[]{int.class},new Object[]{null}));
        Runnable callback=(Runnable)UniversalImages.callback(Runnable.class,ignored->{});
        check(callback.equals(callback));check(!callback.equals(new Object()));callback.run();
        System.out.println("Universal URL, reflection dispatch, and callback checks passed.");
    }
}
