package uz.kinderspa.client;

import android.os.SystemClock;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Fixed origin, bounded JSON, verified platform TLS; redirects never carry credentials. */
public final class ApiClient {
    private final String origin;
    public static final class Failure extends Exception {
        public final int status;
        public final boolean uncertain;
        public Failure(int status, boolean uncertain) { super("request_failed");this.status=status;this.uncertain=uncertain; }
    }
    public ApiClient(String origin,boolean fixture) { this.origin=ApiOrigin.validate(origin,fixture); }
    public JSONObject call(String path,String token,JSONObject body) throws Failure {
        if(!ApiOrigin.configured(origin))throw new Failure(0,false);
        if(!path.matches("/v1/(login|logout|me|subscriptions(\\?after=[1-9][0-9]{0,18})?|bookings(\\?after=[1-9][0-9]{0,18})?|bookings/[1-9][0-9]{0,18}/(qr|cancel))"))throw new Failure(0,false);
        HttpURLConnection connection=null;
        long deadline=SystemClock.elapsedRealtime()+15000;
        try {
            connection=(HttpURLConnection)new URL(origin+path).openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(5000);connection.setReadTimeout(7000);
            connection.setUseCaches(false);connection.setRequestProperty("Accept","application/json");
            connection.setRequestProperty("Accept-Encoding","identity");
            if(token!=null && !token.isEmpty())connection.setRequestProperty("Authorization","Bearer "+token);
            connection.setRequestMethod(body==null?"GET":"POST");
            if(body!=null){byte[] raw=body.toString().getBytes(StandardCharsets.UTF_8);if(raw.length>8192)throw new Failure(0,false);connection.setDoOutput(true);connection.setRequestProperty("Content-Type","application/json");connection.setFixedLengthStreamingMode(raw.length);try(var output=connection.getOutputStream()){output.write(raw);}}
            int status=connection.getResponseCode();
            if(status<200 || status>=300)throw new Failure(status,status>=500 || (body!=null && status>=300 && status<400));
            String contentType=connection.getContentType();
            if(contentType==null || !contentType.toLowerCase(java.util.Locale.ROOT).startsWith("application/json"))throw new Failure(0,true);
            String encoding=connection.getHeaderField("Content-Encoding");
            if(encoding!=null && !encoding.equalsIgnoreCase("identity"))throw new Failure(0,true);
            try(InputStream input=connection.getInputStream();ByteArrayOutputStream bytes=new ByteArrayOutputStream()) {
                byte[] chunk=new byte[4096];int size;
                while((size=input.read(chunk))!=-1){if(bytes.size()+size>131072 || SystemClock.elapsedRealtime()>deadline)throw new Failure(0,true);bytes.write(chunk,0,size);}
                return new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            }
        } catch(Failure failure){throw failure;}catch(Exception ignored){throw new Failure(0,true);}finally{if(connection!=null)connection.disconnect();}
    }
}
