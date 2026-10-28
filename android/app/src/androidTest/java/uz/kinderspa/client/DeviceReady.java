package uz.kinderspa.client;

import android.app.KeyguardManager;
import android.content.Context;
import android.os.ParcelFileDescriptor;
import android.os.PowerManager;
import android.os.SystemClock;
import androidx.test.core.app.ActivityScenario;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;

/** Synthetic emulator preparation only. Never included in a customer APK. */
final class DeviceReady {
    private DeviceReady() {}

    private static void shell(String command) throws IOException {
        try (ParcelFileDescriptor.AutoCloseInputStream result =
                 new ParcelFileDescriptor.AutoCloseInputStream(
                     InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command))) {
            byte[] chunk = new byte[256];
            while (result.read(chunk) != -1) { /* Discard fixed device-command output. */ }
        }
    }

    static void focus(ActivityScenario<MainActivity> scenario) throws IOException {
        shell("input keyevent KEYCODE_WAKEUP");
        shell("wm dismiss-keyguard");
        shell("cmd statusbar collapse");
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        PowerManager power = context.getSystemService(PowerManager.class);
        KeyguardManager keyguard = context.getSystemService(KeyguardManager.class);
        AtomicBoolean focused = new AtomicBoolean();
        long end = SystemClock.elapsedRealtime() + 15000;
        do {
            scenario.onActivity(activity -> focused.set(activity.hasWindowFocus()));
            if (power.isInteractive() && !keyguard.isKeyguardLocked() && focused.get()) return;
            SystemClock.sleep(100);
        } while (SystemClock.elapsedRealtime() < end);
        throw new AssertionError("Synthetic device not ready: interactive=" + power.isInteractive()
            + ",keyguard=" + keyguard.isKeyguardLocked() + ",windowFocus=" + focused.get());
    }
}
