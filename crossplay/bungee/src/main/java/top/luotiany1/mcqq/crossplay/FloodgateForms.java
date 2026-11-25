package top.luotiany1.mcqq.crossplay;

import java.lang.reflect.Method;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.function.IntConsumer;

/** Resolve Cumulus in Floodgate's loader when Geyser ships its own copy. */
final class FloodgateForms {
    private static final String CUMULUS = "org.geysermc.cumulus.";
    private final Method newBuilder;
    private final Method title;
    private final Method content;
    private final Method button;
    private final Method imageButton;
    private final Object pathImage;
    private final Method validResult;
    private final Method closedOrInvalidResult;
    private final Method clickedButtonId;
    private final Method sendForm;

    FloodgateForms(Class<?> api) throws ReflectiveOperationException {
        ClassLoader loader = api.getClassLoader();
        Class<?> simpleForm = loader.loadClass(CUMULUS + "form.SimpleForm");
        Class<?> builder = loader.loadClass(CUMULUS + "form.SimpleForm$Builder");
        Class<?> formBuilder = loader.loadClass(CUMULUS + "form.util.FormBuilder");
        Class<?> imageType = loader.loadClass(CUMULUS + "util.FormImage$Type");
        Class<?> response = loader.loadClass(CUMULUS + "response.SimpleFormResponse");
        newBuilder = simpleForm.getMethod("builder");
        title = builder.getMethod("title", String.class);
        content = builder.getMethod("content", String.class);
        button = builder.getMethod("button", String.class);
        imageButton = builder.getMethod("button", String.class, imageType, String.class);
        pathImage = imageType.getField("PATH").get(null);
        validResult = builder.getMethod("validResultHandler", Consumer.class);
        closedOrInvalidResult = builder.getMethod("closedOrInvalidResultHandler", Runnable.class);
        clickedButtonId = response.getMethod("clickedButtonId");
        sendForm = api.getMethod("sendForm", UUID.class, formBuilder);
    }

    boolean send(Object api, UUID player, BedrockForm form, IntConsumer result) throws ReflectiveOperationException {
        Object builder = newBuilder.invoke(null);
        title.invoke(builder, form.title);
        content.invoke(builder, form.content);
        for (BedrockForm.Button entry : form.buttons) {
            if (entry.texture.isEmpty()) {
                button.invoke(builder, entry.label);
            } else {
                imageButton.invoke(builder, entry.label, pathImage, entry.texture);
            }
        }
        Consumer<Object> onValid = response -> result.accept(readButtonId(response));
        Runnable onClosed = () -> result.accept(BedrockForm.CLOSED);
        validResult.invoke(builder, onValid);
        closedOrInvalidResult.invoke(builder, onClosed);
        return (Boolean) sendForm.invoke(api, player, builder);
    }

    private int readButtonId(Object response) {
        try {
            int index = (Integer) clickedButtonId.invoke(response);
            return index < 0 ? BedrockForm.CLOSED : index;
        } catch (ReflectiveOperationException failure) {
            return BedrockForm.UNAVAILABLE;
        }
    }
}
