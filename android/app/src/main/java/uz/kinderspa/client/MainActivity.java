package uz.kinderspa.client;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Insets;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.view.autofill.AutofillManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import com.google.zxing.BarcodeFormat;
import com.google.zxing.EncodeHintType;
import com.google.zxing.MultiFormatWriter;
import org.json.JSONArray;
import org.json.JSONObject;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Locale;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

public final class MainActivity extends Activity {
    private static final int BLUE=Color.rgb(8,125,181),INK=Color.rgb(23,49,77),MUTED=Color.rgb(87,114,136),PALE=Color.rgb(243,248,252);
    private static final ThreadPoolExecutor IO=new ThreadPoolExecutor(2,2,0,TimeUnit.SECONDS,new ArrayBlockingQueue<>(8));
    private final Handler main=new Handler(Looper.getMainLooper());
    private Session session;
    private ApiClient api;
    private LinearLayout root,content;
    private TextView message;
    private EditText login,password;
    private Button signIn;
    private JSONArray subscriptions=new JSONArray(),bookings=new JSONArray();
    private boolean subscriptionsMore,bookingsMore;
    private String tab="visits";
    private int viewEpoch;
    private AlertDialog qrDialog;
    private ImageView qrImage;
    private TextView qrTimer;
    private Bitmap bitmap;
    private long qrDeadline;
    private boolean resumed;
    private final Runnable qrTick=new Runnable(){public void run(){if(qrDialog==null||!qrDialog.isShowing())return;long left=qrDeadline-SystemClock.elapsedRealtime();if(left<=0){eraseQr();if(qrTimer!=null)qrTimer.setText(R.string.qr_expired);}else{qrTimer.setText(getString(R.string.qr_seconds,(left+999)/1000));main.postDelayed(this,250);}}};

    @Override protected void attachBaseContext(Context context){String language=context.getSharedPreferences("settings",MODE_PRIVATE).getString("language","ru");Configuration c=new Configuration(context.getResources().getConfiguration());c.setLocale(Locale.forLanguageTag(language.equals("uz")?"uz":"ru"));super.attachBaseContext(context.createConfigurationContext(c));}
    @Override public void onCreate(Bundle state){super.onCreate(null);session=((KinderApp)getApplication()).session;api=new ApiClient(BuildConfig.API_ORIGIN,BuildConfig.TEST_FIXTURE&&BuildConfig.DEBUG);if(!BuildConfig.TEST_FIXTURE)getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);render();}
    @Override protected void onStart(){super.onStart();render();}
    @Override protected void onResume(){super.onResume();resumed=true;if(session!=null&&!session.token(SystemClock.elapsedRealtime()).isEmpty())refresh(false);}
    @Override protected void onPause(){resumed=false;viewEpoch++;closeQr();super.onPause();}
    @Override protected void onStop(){resumed=false;viewEpoch++;closeQr();subscriptions=new JSONArray();bookings=new JSONArray();if(content!=null)content.removeAllViews();if(password!=null)password.setText("");super.onStop();}
    @Override protected void onSaveInstanceState(Bundle out){super.onSaveInstanceState(out);out.clear();}
    @Override protected void onDestroy(){viewEpoch++;closeQr();main.removeCallbacksAndMessages(null);super.onDestroy();}

    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private GradientDrawable shape(int color){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(16));return d;}
    private LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);v.setSaveEnabled(false);return v;}
    private TextView text(String value,int size,int color,boolean bold){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setTextColor(color);v.setSaveEnabled(false);if(bold)v.setTypeface(null,Typeface.BOLD);v.setPadding(0,dp(5),0,dp(5));return v;}
    private Button button(String value,int id,Runnable action){Button b=new Button(this);b.setId(id);b.setText(value);b.setAllCaps(false);b.setTextColor(BLUE);b.setMinHeight(dp(48));b.setSaveEnabled(false);b.setBackground(shape(Color.WHITE));b.setOnClickListener(v->action.run());LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(7),0,dp(7));b.setLayoutParams(p);return b;}
    private void addButton(LinearLayout into,int label,int id,Runnable action){into.addView(button(getString(label),id,action));}
    private void render(){
        closeQr();root=column();root.setBackgroundColor(PALE);root.setPadding(dp(20),dp(12),dp(20),dp(12));root.setSaveFromParentEnabled(false);
        root.setOnApplyWindowInsetsListener((v,insets)->{int top,bottom;if(Build.VERSION.SDK_INT>=30){Insets s=insets.getInsets(WindowInsets.Type.systemBars());top=s.top;bottom=Math.max(s.bottom,insets.getInsets(WindowInsets.Type.ime()).bottom);}else{top=insets.getSystemWindowInsetTop();bottom=insets.getSystemWindowInsetBottom();}v.setPadding(dp(20),top+dp(12),dp(20),bottom+dp(12));return insets;});
        LinearLayout brand=new LinearLayout(this);brand.setGravity(Gravity.CENTER_VERTICAL);TextView title=text("Kinder Spa",27,BLUE,true);brand.addView(title,new LinearLayout.LayoutParams(0,-2,1));Button ru=button("RU",R.id.language_ru,()->language("ru")),uz=button("UZ",R.id.language_uz,()->language("uz"));brand.addView(ru,new LinearLayout.LayoutParams(dp(52),dp(48)));brand.addView(uz,new LinearLayout.LayoutParams(dp(52),dp(48)));root.addView(brand);
        root.addView(text(getString(R.string.tagline),13,MUTED,false));
        message=text("",13,MUTED,false);message.setId(R.id.message);message.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);root.addView(message);
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setSaveEnabled(false);content=column();content.setId(R.id.content);scroll.addView(content);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));setContentView(root);
        if(session.token(SystemClock.elapsedRealtime()).isEmpty())renderLogin();else renderSignedIn();
    }
    private void language(String value){getSharedPreferences("settings",MODE_PRIVATE).edit().putString("language",value).apply();recreate();}
    private void renderLogin(){
        content.addView(text(getString(R.string.welcome),29,INK,true));content.addView(text(getString(R.string.issued),14,MUTED,false));
        login=new EditText(this);login.setId(R.id.login);login.setHint(R.string.login_hint);login.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);login.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(64)});login.setSingleLine(true);login.setSaveEnabled(false);login.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);content.addView(login);
        password=new EditText(this);password.setId(R.id.password);password.setHint(R.string.password_hint);password.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);password.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(128)});password.setSingleLine(true);password.setSaveEnabled(false);password.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);content.addView(password);
        signIn=button(getString(R.string.sign_in),R.id.sign_in,this::login);signIn.setBackground(shape(BLUE));signIn.setTextColor(Color.WHITE);content.addView(signIn);
        boolean configured=ApiOrigin.configured(BuildConfig.API_ORIGIN);signIn.setEnabled(configured);login.setEnabled(configured);password.setEnabled(configured);if(!configured)message.setText(R.string.unconfigured);
        content.addView(text(getString(R.string.privacy),12,MUTED,false));licenses();
    }
    private void renderSignedIn(){
        LinearLayout nav=new LinearLayout(this);for(String name:new String[]{"visits","subscriptions","history"}){int label=name.equals("visits")?R.string.visits:name.equals("subscriptions")?R.string.subscriptions:R.string.history;int id=name.equals("visits")?R.id.tab_visits:name.equals("subscriptions")?R.id.tab_subscriptions:R.id.tab_history;Button b=button(getString(label),id,()->{tab=name;showRecords();refresh(false);});b.setMinHeight(dp(64));nav.addView(b,new LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.MATCH_PARENT,1));}root.addView(nav,root.getChildCount()-1);
        LinearLayout controls=new LinearLayout(this);controls.addView(button(getString(R.string.refresh),R.id.refresh,()->refresh(false)),new LinearLayout.LayoutParams(0,dp(50),1));controls.addView(button(getString(R.string.logout),R.id.logout,this::logout),new LinearLayout.LayoutParams(0,dp(50),1));root.addView(controls);
        showRecords();
    }
    private void login(){
        if(!ApiOrigin.configured(BuildConfig.API_ORIGIN))return;
        String name=login.getText().toString(),secret=password.getText().toString();password.setText("");signIn.setEnabled(false);message.setText(R.string.loading);
        final int epoch=++viewEpoch;final long started=SystemClock.elapsedRealtime();
        submit(()->{JSONObject data=null;String issued="";try{data=new JSONObject().put("login",name).put("password",secret);JSONObject result=api.call("/v1/login","",data);issued=result.getString("access_token");if(!issued.matches("[A-Za-z0-9_-]{43}"))throw new ApiClient.Failure(0,false);JSONObject who=api.call("/v1/me",issued,null);if(!"client".equals(who.getString("role"))){try{api.call("/v1/logout",issued,new JSONObject());}catch(Exception ignored){}post(epoch,()->{session.clear();render();message.setText(R.string.client_only);});return;}String newToken=issued;long ttl=result.getLong("expires_in_seconds");if(ttl<=0||ttl>28800)throw new ApiClient.Failure(0,false);post(epoch,()->{session.open(newToken,ttl,started,SystemClock.elapsedRealtime());render();refresh(false);});}catch(ApiClient.Failure failure){post(epoch,()->{signIn.setEnabled(true);message.setText(failure.status==429?R.string.rate_limited:failure.status==401?R.string.auth_failed:R.string.request_failed);});}catch(Exception ignored){post(epoch,()->{signIn.setEnabled(true);message.setText(R.string.request_failed);});}finally{if(data!=null)data.remove("password");}});
    }
    private interface Work{void run();}
    private void submit(Work work){try{IO.execute(work::run);}catch(RuntimeException ignored){message.setText(R.string.request_failed);if(signIn!=null)signIn.setEnabled(ApiOrigin.configured(BuildConfig.API_ORIGIN));}}
    private void post(int epoch,Runnable result){main.post(()->{if(resumed&&!isFinishing()&&epoch==viewEpoch)result.run();});}
    private String currentToken(){String value=session.token(SystemClock.elapsedRealtime());if(value.isEmpty()){session.clear();render();message.setText(R.string.session_expired);}return value;}
    private void fail(int epoch,ApiClient.Failure failure){post(epoch,()->{if(failure.status==401){session.clear();subscriptions=new JSONArray();bookings=new JSONArray();render();message.setText(R.string.session_expired);}else message.setText(failure.status==409||failure.status==403?R.string.operation_rejected:R.string.request_failed);});}
    private void refresh(boolean more){
        String token=currentToken();if(token.isEmpty())return;final int epoch=++viewEpoch;message.setText(R.string.loading);
        final boolean sub=tab.equals("subscriptions");JSONArray before=more?(sub?subscriptions:bookings):new JSONArray();long after=0;try{if(more&&before.length()>0)after=before.getJSONObject(before.length()-1).getLong(sub?"subscription_id":"booking_id");}catch(Exception ignored){message.setText(R.string.request_failed);return;}
        String path=(sub?"/v1/subscriptions":"/v1/bookings")+(after>0?"?after="+after:"");
        submit(()->{try{JSONObject result=api.call(path,token,null);JSONArray page=result.getJSONArray("items");if(page.length()>50)throw new ApiClient.Failure(0,false);JSONArray combined=new JSONArray();for(int i=0;i<before.length();i++)combined.put(before.getJSONObject(i));for(int i=0;i<page.length();i++)combined.put(page.getJSONObject(i));post(epoch,()->{if(sub){subscriptions=combined;subscriptionsMore=page.length()==50;}else{bookings=combined;bookingsMore=page.length()==50;}message.setText("");showRecords();});}catch(ApiClient.Failure failure){fail(epoch,failure);}catch(Exception ignored){fail(epoch,new ApiClient.Failure(0,false));}});
    }
    private void showRecords(){
        if(content==null)return;content.removeAllViews();content.addView(text(getString(tab.equals("subscriptions")?R.string.subscriptions:tab.equals("history")?R.string.history:R.string.visits),25,INK,true));
        JSONArray rows=tab.equals("subscriptions")?subscriptions:bookings;int shown=0;
        try{for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(!tab.equals("subscriptions")&&tab.equals("history")=="reserved".equals(row.getString("state")))continue;LinearLayout card=column();card.setBackground(shape(Color.WHITE));card.setPadding(dp(17),dp(12),dp(17),dp(12));LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,-2);layout.setMargins(0,dp(8),0,dp(8));card.setLayoutParams(layout);
            if(tab.equals("subscriptions")){card.addView(text(getString(R.string.subscription_id,row.getLong("subscription_id")),17,INK,true));JSONArray allowances=row.getJSONArray("allowances");for(int j=0;j<allowances.length();j++){JSONObject a=allowances.getJSONObject(j);card.addView(text(service(a.getString("category")),15,BLUE,true));card.addView(text(getString(R.string.remaining,a.getLong("remaining"),a.getLong("quota")),14,MUTED,false));}}
            else{long booking=row.getLong("booking_id");card.addView(text(service(row.getString("category")),19,INK,true));card.addView(text(getString(R.string.booking_id,booking),12,MUTED,false));String stamp=OffsetDateTime.parse(row.getString("starts_at")).atZoneSameInstant(ZoneId.of("Asia/Tashkent")).format(DateTimeFormatter.ofPattern("dd.MM.yyyy · HH:mm"));card.addView(text(stamp,15,INK,false));card.addView(text(state(row.getString("state")),13,BLUE,true));if("reserved".equals(row.getString("state"))){card.addView(button(getString(R.string.show_qr),View.generateViewId(),()->qr(booking)));if("pool".equals(row.getString("category")))card.addView(button(getString(R.string.cancel_booking),View.generateViewId(),()->confirmCancel(booking)));}}
            content.addView(card);shown++;}
        }catch(Exception ignored){message.setText(R.string.request_failed);}
        if(shown==0)content.addView(text(getString(R.string.empty),15,MUTED,false));
        content.addView(text(getString(R.string.loaded),11,MUTED,false));content.addView(text(getString(R.string.tashkent),11,MUTED,false));
        if((tab.equals("subscriptions")?subscriptionsMore:bookingsMore)&&rows.length()<500)addButton(content,R.string.more,View.generateViewId(),()->refresh(true));
    }
    private String service(String value){return getString(value.equals("pool")?R.string.pool:value.equals("massage")?R.string.massage:R.string.hydromassage);}
    private String state(String value){return getString(switch(value){case "reserved"->R.string.reserved;case "consumed"->R.string.consumed;case "cancelled"->R.string.cancelled;case "forfeited"->R.string.forfeited;case "no_show"->R.string.no_show;default->R.string.restored;});}
    private void confirmCancel(long booking){new AlertDialog.Builder(this).setTitle(R.string.cancel_title).setMessage(R.string.cancel_policy).setNegativeButton(R.string.back,null).setPositiveButton(R.string.confirm_cancel,(d,w)->cancel(booking)).show();}
    private void cancel(long booking){String token=currentToken();if(token.isEmpty())return;final int epoch=++viewEpoch;message.setText(R.string.loading);String key=session.cancellationKey(booking);long sessionGeneration=session.generation();submit(()->{try{api.call("/v1/bookings/"+booking+"/cancel",token,new JSONObject().put("key",key));session.confirmed(booking,sessionGeneration);main.post(()->{if(resumed&&!isFinishing()&&session.generation()==sessionGeneration){message.setText(R.string.cancel_saved);refresh(false);}});}catch(ApiClient.Failure failure){if(!failure.uncertain)session.confirmed(booking,sessionGeneration);if(failure.uncertain)post(epoch,()->message.setText(R.string.cancel_unknown));else fail(epoch,failure);}catch(Exception ignored){post(epoch,()->message.setText(R.string.cancel_unknown));}});}
    private void qr(long booking){String token=currentToken();if(token.isEmpty())return;closeQr();final int epoch=++viewEpoch;final long started=SystemClock.elapsedRealtime();message.setText(R.string.loading);submit(()->{try{JSONObject result=api.call("/v1/bookings/"+booking+"/qr",token,new JSONObject());String raw=result.getString("token");if(!raw.matches("[A-Za-z0-9_-]{43}"))throw new ApiClient.Failure(0,false);long until=Session.deadline(result.getLong("valid_for_seconds"),started,SystemClock.elapsedRealtime(),120);HashMap<EncodeHintType,Object> hints=new HashMap<>();hints.put(EncodeHintType.MARGIN,4);var matrix=new MultiFormatWriter().encode(raw,BarcodeFormat.QR_CODE,512,512,hints);Bitmap image=Bitmap.createBitmap(512,512,Bitmap.Config.RGB_565);for(int y=0;y<512;y++)for(int x=0;x<512;x++)image.setPixel(x,y,matrix.get(x,y)?Color.BLACK:Color.WHITE);main.post(()->{if(resumed&&!isFinishing()&&epoch==viewEpoch){message.setText("");displayQr(booking,image,until);}else{image.eraseColor(Color.WHITE);image.recycle();}});}catch(ApiClient.Failure failure){fail(epoch,failure);}catch(Exception ignored){fail(epoch,new ApiClient.Failure(0,false));}});}
    private void displayQr(long booking,Bitmap image,long until){closeQr();bitmap=image;qrDeadline=until;LinearLayout box=column();box.setPadding(dp(20),dp(10),dp(20),dp(10));box.addView(text(getString(R.string.qr_help),14,MUTED,false));qrImage=new ImageView(this);qrImage.setId(R.id.qr_image);qrImage.setContentDescription(getString(R.string.qr_accessible));qrImage.setImageBitmap(bitmap);box.addView(qrImage,new LinearLayout.LayoutParams(-1,dp(260)));qrTimer=text("",14,INK,true);qrTimer.setId(R.id.qr_timer);box.addView(qrTimer);box.addView(button(getString(R.string.qr_refresh),R.id.qr_refresh,()->qr(booking)));qrDialog=new AlertDialog.Builder(this).setTitle(R.string.qr_title).setView(box).setNegativeButton(R.string.close,(d,w)->closeQr()).create();if(!BuildConfig.TEST_FIXTURE)qrDialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);AlertDialog created=qrDialog;qrDialog.setOnDismissListener(d->{if(qrDialog==created){main.removeCallbacks(qrTick);eraseQr();qrDialog=null;qrImage=null;qrTimer=null;}});qrDialog.show();main.post(qrTick);}
    private void eraseQr(){if(qrImage!=null){qrImage.setImageDrawable(null);qrImage.setVisibility(View.INVISIBLE);}if(bitmap!=null){bitmap.eraseColor(Color.WHITE);bitmap.recycle();bitmap=null;}}
    private void closeQr(){main.removeCallbacks(qrTick);AlertDialog old=qrDialog;qrDialog=null;eraseQr();qrImage=null;qrTimer=null;if(old!=null)old.dismiss();}
    private void logout(){String old=session.token(SystemClock.elapsedRealtime());session.clear();viewEpoch++;subscriptions=new JSONArray();bookings=new JSONArray();render();final int epoch=viewEpoch;submit(()->{try{api.call("/v1/logout",old,new JSONObject());}catch(Exception ignored){post(epoch,()->message.setText(R.string.local_logout));}});}
    private String licenseText(){try(var input=getAssets().open("third_party_notices.txt");var reader=new java.io.BufferedReader(new java.io.InputStreamReader(input,java.nio.charset.StandardCharsets.UTF_8))){return reader.lines().collect(java.util.stream.Collectors.joining("\n"));}catch(Exception ignored){return getString(R.string.license_text);}}
    private void licenses(){addButton(content,R.string.licenses,View.generateViewId(),()->new AlertDialog.Builder(this).setTitle(R.string.licenses).setMessage(licenseText()).setPositiveButton(R.string.close,null).show());}
}
