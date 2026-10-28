package uz.kinderspa.client;

import org.junit.Test;
import static org.junit.Assert.*;

public class SessionTest {
    private static final String TOKEN="a".repeat(43);
    @Test public void startsEmpty(){assertEquals("",new Session().token(1000));}
    @Test public void opensWithMonotonicExpiry(){Session s=new Session();s.open(TOKEN,60,1000,2000);assertEquals(TOKEN,s.token(59999));assertEquals("",s.token(61000));}
    @Test public void roundTripIsDeducted(){assertEquals(11000,Session.deadline(10,1000,4000,120));}
    @Test public void expiredResponseHasNoRemainingTime(){assertEquals(15000,Session.deadline(1,1000,15000,120));}
    @Test public void rejectsBadTokens(){for(String value:new String[]{"","a".repeat(42),"a".repeat(44),"\n".repeat(43)}){try{new Session().open(value,60,1,2);fail();}catch(IllegalArgumentException expected){}}}
    @Test public void rejectsBadSessionLifetimes(){for(long value:new long[]{0,-1,28801}){try{new Session().open(TOKEN,value,1,2);fail();}catch(IllegalArgumentException expected){}}}
    @Test public void clearInvalidatesTokenAndGeneration(){Session s=new Session();s.open(TOKEN,60,1,2);long prior=s.generation();s.clear();assertTrue(s.generation()>prior);assertEquals("",s.token(3));}
    @Test public void cancellationRetryKeepsExactKey(){Session s=new Session();assertEquals(s.cancellationKey(2),s.cancellationKey(2));assertNotEquals(s.cancellationKey(2),s.cancellationKey(3));}
    @Test public void staleConfirmationCannotChangeNewSessionKey(){Session s=new Session();s.open(TOKEN,60,1,2);long generation=s.generation();s.clear();String key=s.cancellationKey(1);s.confirmed(1,generation);assertEquals(key,s.cancellationKey(1));}
    @Test public void confirmationAllowsNextOperation(){Session s=new Session();String old=s.cancellationKey(1);s.confirmed(1,s.generation());assertNotEquals(old,s.cancellationKey(1));}
}
