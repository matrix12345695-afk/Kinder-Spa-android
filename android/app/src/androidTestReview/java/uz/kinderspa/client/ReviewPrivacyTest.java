package uz.kinderspa.client;

import android.content.Intent;
import android.view.WindowManager;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.core.app.ActivityScenario;
import static androidx.test.espresso.Espresso.*;
import static androidx.test.espresso.matcher.ViewMatchers.*;
import static androidx.test.espresso.assertion.ViewAssertions.*;
import static org.hamcrest.Matchers.*;
import static org.junit.Assert.*;
import org.junit.*;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ReviewPrivacyTest {
    @Test public void realReviewApkHasNoCleartextOrConfiguredServer(){try(ActivityScenario<MainActivity> scenario=ActivityScenario.launch(MainActivity.class)){assertFalse(BuildConfig.TEST_FIXTURE);assertEquals("https://example.invalid",BuildConfig.API_ORIGIN);scenario.onActivity(activity->assertTrue((activity.getWindow().getAttributes().flags&WindowManager.LayoutParams.FLAG_SECURE)!=0));onView(withId(R.id.sign_in)).check(matches(not(isEnabled())));assertFalse(android.security.NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted());}}
}
