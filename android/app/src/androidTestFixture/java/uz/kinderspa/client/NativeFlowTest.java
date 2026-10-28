package uz.kinderspa.client;

import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.drawable.BitmapDrawable;
import android.os.SystemClock;
import android.view.View;
import android.widget.ImageView;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.core.app.ActivityScenario;
import androidx.lifecycle.Lifecycle;
import static androidx.test.espresso.Espresso.*;
import static androidx.test.espresso.action.ViewActions.*;
import static androidx.test.espresso.assertion.ViewAssertions.*;
import static androidx.test.espresso.matcher.ViewMatchers.*;
import static org.hamcrest.Matchers.*;
import static org.junit.Assert.*;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.RGBLuminanceSource;
import com.google.zxing.common.HybridBinarizer;
import org.json.JSONObject;
import org.junit.*;
import org.junit.runner.RunWith;
import org.junit.runners.MethodSorters;
import java.io.File;
import java.io.FileOutputStream;
import java.util.concurrent.atomic.AtomicReference;

@RunWith(AndroidJUnit4.class) @FixMethodOrder(MethodSorters.NAME_ASCENDING)
public class NativeFlowTest {
    private ActivityScenario<MainActivity> scenario;
    private static final String PASSWORD="synthetic-fixture-password-1";
    private MainActivity activity;
    @Before public void start()throws Exception{var target=InstrumentationRegistry.getInstrumentation().getTargetContext();((KinderApp)target.getApplicationContext()).session.clear();target.getSharedPreferences("settings",0).edit().putString("language","ru").commit();scenario=ActivityScenario.launch(MainActivity.class);scenario.onActivity(a->activity=a);DeviceReady.focus(scenario);}
    @After public void finish(){if(scenario!=null)scenario.close();}
    private androidx.test.espresso.ViewInteraction qrView(int id){return onView(withId(id)).inRoot(androidx.test.espresso.matcher.RootMatchers.isDialog());}
    private void waitId(int id){long end=SystemClock.elapsedRealtime()+20000;AssertionError failure=null;do{try{(id==R.id.qr_image?qrView(id):onView(withId(id))).check(matches(isDisplayed()));return;}catch(AssertionError|androidx.test.espresso.NoMatchingViewException e){if(e instanceof AssertionError)failure=(AssertionError)e;SystemClock.sleep(100);}}while(SystemClock.elapsedRealtime()<end);if(failure!=null)throw failure;throw new AssertionError("native UI state timeout");}
    private void waitText(String text){long end=SystemClock.elapsedRealtime()+20000;do{try{onView(withText(text)).check(matches(isDisplayed()));return;}catch(AssertionError|androidx.test.espresso.NoMatchingViewException e){SystemClock.sleep(100);}}while(SystemClock.elapsedRealtime()<end);throw new AssertionError("native text state timeout");}
    private void signIn(int number){onView(withId(R.id.login)).perform(replaceText("android_fixture_"+String.format(java.util.Locale.ROOT,"%02d",number)));onView(withId(R.id.password)).perform(replaceText(PASSWORD),androidx.test.espresso.action.ViewActions.closeSoftKeyboard());onView(withId(R.id.sign_in)).perform(click());waitId(R.id.logout);waitText("Показать QR");}
    private void shot(String name)throws Exception{
        assertTrue(BuildConfig.TEST_FIXTURE);
        if(name.startsWith("visits-"))waitText(name.endsWith("uz.png")?"QR ko‘rsatish":"Показать QR");
        if(name.equals("subscriptions-ru.png"))waitText("Осталось: 3 из 4");
        if(name.equals("history-ru.png"))waitText("Отменено с возвратом");
        long end=SystemClock.elapsedRealtime()+10000;
        while(true){try{onView(withId(R.id.message)).check(matches(withText("")));break;}catch(AssertionError e){if(SystemClock.elapsedRealtime()>=end)throw e;SystemClock.sleep(100);}}
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();
        java.util.concurrent.CountDownLatch frame=new java.util.concurrent.CountDownLatch(1);
        scenario.onActivity(a->{View decor=a.getWindow().getDecorView();if(android.os.Build.VERSION.SDK_INT>=29&&decor.isHardwareAccelerated()){decor.getViewTreeObserver().registerFrameCommitCallback(frame::countDown);decor.invalidate();}else decor.postDelayed(frame::countDown,300);});
        assertTrue("synthetic screen frame was not committed",frame.await(5,java.util.concurrent.TimeUnit.SECONDS));
        InstrumentationRegistry.getInstrumentation().getUiAutomation().waitForIdle(250,5000);
        File folder=new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getExternalFilesDir(null),"native-evidence");
        assertTrue(folder.exists()||folder.mkdirs());
        Bitmap image=InstrumentationRegistry.getInstrumentation().getUiAutomation().takeScreenshot();
        try(FileOutputStream output=new FileOutputStream(new File(folder,name))){assertTrue(image.compress(Bitmap.CompressFormat.PNG,100,output));}image.recycle();
    }
    private void assertNavigationTextFits(){scenario.onActivity(a->{for(int id:new int[]{R.id.tab_visits,R.id.tab_subscriptions,R.id.tab_history}){android.widget.TextView view=a.findViewById(id);assertNotNull(view.getLayout());assertTrue("localized navigation text is clipped",view.getLayout().getHeight()<=view.getHeight()-view.getTotalPaddingTop()-view.getTotalPaddingBottom());for(int line=0;line<view.getLayout().getLineCount();line++)assertEquals(0,view.getLayout().getEllipsisCount(line));}});}
    @Test public void test01_loginAndOwnSubscriptions()throws Exception{shot("login-ru.png");signIn(1);shot("visits-ru.png");onView(withId(R.id.tab_subscriptions)).perform(click());waitText("Осталось: 3 из 4");onView(withText("Осталось: 10 из 10")).check(matches(isDisplayed()));shot("subscriptions-ru.png");}
    @Test public void test02_realQrContainsOnlyOneTimeOpaqueToken()throws Exception{signIn(2);onView(withText("Показать QR")).perform(click());waitId(R.id.qr_image);AtomicReference<Bitmap> image=new AtomicReference<>();qrView(R.id.qr_image).perform(new androidx.test.espresso.ViewAction(){public org.hamcrest.Matcher<View> getConstraints(){return isAssignableFrom(ImageView.class);}public String getDescription(){return "read synthetic QR bitmap";}public void perform(androidx.test.espresso.UiController controller,View view){image.set(((BitmapDrawable)((ImageView)view).getDrawable()).getBitmap().copy(Bitmap.Config.ARGB_8888,false));}});Bitmap value=image.get();int[] pixels=new int[value.getWidth()*value.getHeight()];value.getPixels(pixels,0,value.getWidth(),0,0,value.getWidth(),value.getHeight());String token=new MultiFormatReader().decode(new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(value.getWidth(),value.getHeight(),pixels)))).getText();assertTrue(token.matches("[A-Za-z0-9_-]{43}"));value.recycle();}
    @Test public void test03_qrExpiresUsingMonotonicServerLifetime()throws Exception{signIn(3);onView(withText("Показать QR")).perform(click());waitId(R.id.qr_image);long end=SystemClock.elapsedRealtime()+20000;while(true){try{onView(withText("Срок кода истёк. Обновите QR.")).inRoot(androidx.test.espresso.matcher.RootMatchers.isDialog()).check(matches(isDisplayed()));break;}catch(AssertionError|androidx.test.espresso.NoMatchingViewException e){if(SystemClock.elapsedRealtime()>=end)throw e;SystemClock.sleep(100);}}qrView(R.id.qr_image).check(matches(withEffectiveVisibility(Visibility.INVISIBLE)));}
    @Test public void test04_poolCancellationUsesRealAccounting()throws Exception{signIn(4);onView(withText("Отменить запись")).perform(click());onView(withText("Подтвердить отмену")).perform(click());onView(withId(R.id.tab_subscriptions)).perform(click());waitText("Осталось: 4 из 4");onView(withId(R.id.tab_history)).perform(click());waitText("Отменено с возвратом");shot("history-ru.png");}
    @Test public void test05_logoutClearsSession()throws Exception{signIn(5);onView(withId(R.id.logout)).perform(click());waitId(R.id.sign_in);assertEquals("",((KinderApp)activity.getApplication()).session.token(SystemClock.elapsedRealtime()));onView(withId(R.id.password)).check(matches(withText("")));}
    @Test public void test06_russianUzbekSwitch()throws Exception{onView(withId(R.id.language_uz)).perform(click());waitText("Kirish");shot("login-uz.png");onView(withId(R.id.login)).perform(replaceText("android_fixture_06"));onView(withId(R.id.password)).perform(replaceText(PASSWORD),androidx.test.espresso.action.ViewActions.closeSoftKeyboard());onView(withId(R.id.sign_in)).perform(click());waitId(R.id.logout);waitText("QR ko‘rsatish");assertNavigationTextFits();shot("visits-uz.png");}
    @Test public void test07_backgroundClearsQr()throws Exception{signIn(7);onView(withText("Показать QR")).perform(click());waitId(R.id.qr_image);scenario.moveToState(Lifecycle.State.CREATED);scenario.moveToState(Lifecycle.State.RESUMED);waitId(R.id.logout);onView(withId(R.id.qr_image)).check(doesNotExist());}
    @Test public void test08_recreationKeepsOnlyProcessSession()throws Exception{signIn(8);scenario.recreate();scenario.onActivity(a->activity=a);waitId(R.id.logout);assertEquals(1,activity.getSharedPreferences("settings",0).getAll().size());}
    @Test public void test09_staffCannotEnterClientApplication()throws Exception{onView(withId(R.id.login)).perform(replaceText("admin_fixture"));onView(withId(R.id.password)).perform(replaceText(PASSWORD),androidx.test.espresso.action.ViewActions.closeSoftKeyboard());onView(withId(R.id.sign_in)).perform(click());waitText("Это приложение для клиентов. Сотрудникам доступна веб-панель.");onView(withId(R.id.sign_in)).check(matches(isDisplayed()));}
    @Test public void test10_wrongPasswordDoesNotLeaveInput()throws Exception{onView(withId(R.id.login)).perform(replaceText("android_fixture_10"));onView(withId(R.id.password)).perform(replaceText("synthetic-wrong-password"),androidx.test.espresso.action.ViewActions.closeSoftKeyboard());onView(withId(R.id.sign_in)).perform(click());waitText("Проверьте логин и пароль.");onView(withId(R.id.password)).check(matches(withText("")));}
}
