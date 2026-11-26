package top.luotiany1.mcqq.crossplay;

import java.lang.reflect.Method;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.UUID;

public final class FloodgateFormsTest {
    private static final String FORM_BUILDER = "org.geysermc.cumulus.form.util.FormBuilder";

    // Pass the two proxy plugin JARs as arguments and keep them off the parent classpath.
    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("Expected the Floodgate and Geyser plugin JAR paths");
        }
        ClassLoader parent = FloodgateFormsTest.class.getClassLoader();
        try (URLClassLoader floodgate = new URLClassLoader(new URL[]{Paths.get(args[0]).toUri().toURL()}, parent);
             URLClassLoader geyser = new URLClassLoader(new URL[]{Paths.get(args[1]).toUri().toURL()}, parent)) {
            Class<?> floodgateBuilder = floodgate.loadClass(FORM_BUILDER);
            Class<?> geyserBuilder = geyser.loadClass(FORM_BUILDER);
            if (floodgateBuilder == geyserBuilder) {
                throw new AssertionError("The fixtures must load independent Cumulus copies");
            }

            Class<?> api = floodgate.loadClass("org.geysermc.floodgate.api.FloodgateApi");
            Object instance = floodgate.loadClass("org.geysermc.floodgate.api.SimpleFloodgateApi")
                    .getConstructor().newInstance();
            UUID player = UUID.randomUUID();
            Method oldDispatch = api.getMethod("sendForm", UUID.class, floodgateBuilder);
            Object foreignBuilder = geyser.loadClass("org.geysermc.cumulus.form.SimpleForm")
                    .getMethod("builder").invoke(null);
            try {
                oldDispatch.invoke(instance, player, foreignBuilder);
                throw new AssertionError("Floodgate accepted a builder from Geyser's loader");
            } catch (IllegalArgumentException expected) {
                // The direct JVM invocation fails with a loader constraint violation in BungeeCord.
            }

            BedrockForm form = new BedrockForm("Shop", "Choose an item", Arrays.asList(
                    new BedrockForm.Button("Back"), new BedrockForm.Button("Buy", "textures/items/apple")));
            boolean accepted = new FloodgateForms(api).send(instance, player, form, index -> {
                throw new AssertionError("No Bedrock player is registered in this fixture");
            });
            if (!accepted) {
                throw new AssertionError("Floodgate could not build the form");
            }
            System.out.println("Floodgate rejected Geyser's Cumulus builder and accepted the adapter's form.");
        }
    }
}
