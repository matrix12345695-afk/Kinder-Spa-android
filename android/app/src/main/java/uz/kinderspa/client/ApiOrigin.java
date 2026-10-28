package uz.kinderspa.client;

import java.net.URI;

/** An API origin comes from the reviewed build, never from a login field/link/QR. */
public final class ApiOrigin {
    public static String validate(String origin, boolean fixture) {
        if(fixture && "http://10.0.2.2:18763".equals(origin))return origin;
        try {
            URI value=new URI(origin);
            if(!"https".equals(value.getScheme()) || value.getHost()==null || value.getRawUserInfo()!=null || value.getRawQuery()!=null || value.getRawFragment()!=null || !"".equals(value.getRawPath()) || value.getPort()==0 || value.getPort()>65535 || !origin.matches("https://[a-z0-9.-]+(:[1-9][0-9]{0,4})?"))throw new IllegalArgumentException();
            return origin;
        } catch(Exception ignored) { throw new IllegalArgumentException("invalid_api_origin"); }
    }
    public static boolean configured(String origin) { return !"https://example.invalid".equals(origin); }
    private ApiOrigin() {}
}
