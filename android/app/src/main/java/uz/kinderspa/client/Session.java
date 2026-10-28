package uz.kinderspa.client;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/** Process memory only; monotonic expiry must include deep sleep. No Android storage. */
public final class Session {
    private String token = "";
    private long expiresElapsed;
    private long generation;
    private final Map<Long,String> cancellationKeys = new HashMap<>();

    public synchronized long generation() { return generation; }
    public synchronized void clear() { token=""; expiresElapsed=0; generation++; cancellationKeys.clear(); }
    public synchronized void open(String value, long ttlSeconds, long requestStarted, long nowElapsed) {
        if (value==null || !value.matches("[A-Za-z0-9_-]{43}") || ttlSeconds<=0 || ttlSeconds>28800 || requestStarted>nowElapsed) throw new IllegalArgumentException("invalid_session");
        clear(); token=value;
        expiresElapsed=deadline(ttlSeconds,requestStarted,nowElapsed,28800);
    }
    public synchronized String token(long nowElapsed) {
        if (nowElapsed>=expiresElapsed || nowElapsed<0) { if(!token.isEmpty())clear(); return ""; }
        return token;
    }
    public synchronized String cancellationKey(long booking) { if(booking<=0)throw new IllegalArgumentException("invalid_booking"); return cancellationKeys.computeIfAbsent(booking,k->UUID.randomUUID().toString()); }
    public synchronized void confirmed(long booking,long expectedGeneration) { if(expectedGeneration==generation)cancellationKeys.remove(booking); }
    public static long deadline(long seconds,long started,long now,long maximum) {
        if(seconds<0 || seconds>maximum || started<0 || now<started)throw new IllegalArgumentException("invalid_lifetime");
        long remaining=Math.max(0,seconds*1000-(now-started));
        return now+remaining;
    }
}
