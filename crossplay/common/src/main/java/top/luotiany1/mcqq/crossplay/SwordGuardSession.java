package top.luotiany1.mcqq.crossplay;

final class SwordGuardSession<P> {
    private static final String INPUT = "bwcombat:sword_guard_input";
    private static final String STATE = "bwcombat:sword_guard_state";
    private static final int PULSE_INTERVAL = 4;
    private final GalApi<P> api;
    private boolean wasHeld;
    private int ticksToPulse;
    private volatile boolean confirmed;

    SwordGuardSession(GalApi<P> api) {
        this.api = api;
    }

    void register() {
        api.onEvent(STATE, (peer, bytes) -> {
            if (bytes.length == 1 && (bytes[0] == 0 || bytes[0] == 1)
                    && api.canSendEvent(peer, INPUT)) {
                confirmed = bytes[0] == 1;
            }
        });
    }

    void tick(P peer, boolean held) {
        if (!api.canSendEvent(peer, INPUT)) {
            reset();
            return;
        }
        if (held) {
            if (!wasHeld || --ticksToPulse <= 0) {
                api.sendEvent(peer, INPUT, new byte[] {1});
                ticksToPulse = PULSE_INTERVAL;
            }
        } else {
            if (wasHeld || confirmed) {
                api.sendEvent(peer, INPUT, new byte[] {0});
            }
            confirmed = false;
        }
        wasHeld = held;
    }

    boolean showPose() {
        return confirmed;
    }

    void reset() {
        confirmed = false;
        wasHeld = false;
        ticksToPulse = 0;
    }
}
