package uz.kinderspa.client;

import org.junit.Test;
import static org.junit.Assert.*;

public class ApiOriginTest {
    @Test public void exactHttpsOrigin(){assertEquals("https://api.example:8443",ApiOrigin.validate("https://api.example:8443",false));}
    @Test public void runtimeCannotSelectHttp(){for(String value:new String[]{"http://example.com","http://10.0.2.2:18763","file:///etc/passwd"})reject(value,false);}
    @Test public void rejectsCredentialsPathsQueriesAndFragments(){for(String value:new String[]{"https://user:pass@api.example","https://api.example/","https://api.example/path","https://api.example?q=secret","https://api.example#secret"})reject(value,false);}
    @Test public void onlyExactEmulatorException(){assertEquals("http://10.0.2.2:18763",ApiOrigin.validate("http://10.0.2.2:18763",true));reject("http://127.0.0.1:18763",true);reject("http://10.0.2.2:18764",true);}
    @Test public void badPortsRejected(){reject("https://api.example:0",false);reject("https://api.example:65536",false);}
    @Test public void reviewBuildDoesNotPretendToHaveServer(){assertFalse(ApiOrigin.configured("https://example.invalid"));assertTrue(ApiOrigin.configured("https://approved.example"));}
    private void reject(String value,boolean fixture){try{ApiOrigin.validate(value,fixture);fail(value);}catch(IllegalArgumentException expected){}}
}
