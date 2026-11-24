package app.mochi.pet;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.ArrayList;

/**
 * Mochi's phone app. A full-screen WebView:
 *  1. starts on finder.html (in the app), which looks for Mochi: the last address, her own hotspot
 *     (the Wi-Fi gateway, 10.42.0.1), mochi.local, and the network service "_mochi._tcp" (mDNS, via NsdManager);
 *  2. opens her app from the Pi itself (http://<pet>:8080), so app updates come with the pet's code;
 *  3. gives the page a small bridge "MochiApp": voice input (Android speech recognition), find again, address.
 */
public class MainActivity extends Activity {
    static final String FINDER = "file:///android_asset/finder.html";
    WebView web;
    SharedPreferences prefs;
    NsdManager nsd;
    NsdManager.DiscoveryListener discovery;
    WifiManager.MulticastLock mlock;
    SpeechRecognizer recognizer;
    final Handler ui = new Handler(Looper.getMainLooper());
    final ArrayDeque<NsdServiceInfo> toResolve = new ArrayDeque<>();
    boolean resolving = false;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        // cream bars with dark icons in light mode, ink bars in dark mode (matches the page)
        boolean night = (getResources().getConfiguration().uiMode
                & android.content.res.Configuration.UI_MODE_NIGHT_MASK) == android.content.res.Configuration.UI_MODE_NIGHT_YES;
        int bg = night ? 0xFF0B1F1C : 0xFFF2FAF7;
        if (!night && android.os.Build.VERSION.SDK_INT >= 23) {
            int f = android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (android.os.Build.VERSION.SDK_INT >= 26) f |= 0x10;   // SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
            getWindow().getDecorView().setSystemUiVisibility(f);
            getWindow().setStatusBarColor(bg);
            getWindow().setNavigationBarColor(android.os.Build.VERSION.SDK_INT >= 26 ? bg : 0xFF0B1F1C);
        } else {
            getWindow().setStatusBarColor(0xFF0B1F1C);
            getWindow().setNavigationBarColor(0xFF0B1F1C);
        }
        prefs = getSharedPreferences("mochi", MODE_PRIVATE);
        web = new WebView(this);
        web.setBackgroundColor(bg);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        web.addJavascriptInterface(new Bridge(), "MochiApp");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame() && !req.getUrl().toString().startsWith("file:")) {
                    v.loadUrl(FINDER + "?lost=1");          // lost her: back to searching
                }
            }
        });
        setContentView(web);
        web.loadUrl(FINDER);
    }

    void js(final String code) {
        ui.post(new Runnable() { public void run() { web.evaluateJavascript(code, null); } });
    }

    // ---- finding Mochi on the network (mDNS) ----------------------------------------------------
    void startDiscovery() {
        stopDiscovery();
        nsd = (NsdManager) getSystemService(Context.NSD_SERVICE);
        WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        mlock = wm.createMulticastLock("mochi");
        mlock.setReferenceCounted(false);
        mlock.acquire();
        discovery = new NsdManager.DiscoveryListener() {
            public void onDiscoveryStarted(String t) {}
            public void onDiscoveryStopped(String t) {}
            public void onStartDiscoveryFailed(String t, int e) { js("window.onDiscoveryError&&onDiscoveryError(" + e + ")"); }
            public void onStopDiscoveryFailed(String t, int e) {}
            public void onServiceLost(NsdServiceInfo i) {}
            public void onServiceFound(NsdServiceInfo info) {
                synchronized (toResolve) { toResolve.add(info); }
                resolveNext();
            }
        };
        nsd.discoverServices("_mochi._tcp", NsdManager.PROTOCOL_DNS_SD, discovery);
    }

    void resolveNext() {
        NsdServiceInfo next;
        synchronized (toResolve) {
            if (resolving || toResolve.isEmpty()) return;
            resolving = true;
            next = toResolve.poll();
        }
        nsd.resolveService(next, new NsdManager.ResolveListener() {
            public void onResolveFailed(NsdServiceInfo i, int e) { done(); }
            public void onServiceResolved(NsdServiceInfo i) {
                if (i.getHost() != null) {
                    String url = "http://" + i.getHost().getHostAddress() + ":" + i.getPort();
                    js("window.onRobot&&onRobot(" + JSONObject.quote(i.getServiceName()) + "," + JSONObject.quote(url) + ")");
                }
                done();
            }
            void done() { synchronized (toResolve) { resolving = false; } resolveNext(); }
        });
    }

    void stopDiscovery() {
        try { if (nsd != null && discovery != null) nsd.stopServiceDiscovery(discovery); } catch (Exception ignored) {}
        discovery = null;
        if (mlock != null && mlock.isHeld()) mlock.release();
    }

    // ---- voice input ---------------------------------------------------------------------------
    void listen() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 7);
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) { js("onSpeech('')"); return; }
        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(this);
            recognizer.setRecognitionListener(new RecognitionListener() {
                public void onResults(Bundle b) {
                    ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    js("onSpeech(" + JSONObject.quote(r != null && !r.isEmpty() ? r.get(0) : "") + ")");
                }
                public void onError(int e) { js("onSpeech('')"); }
                public void onReadyForSpeech(Bundle b) {}
                public void onBeginningOfSpeech() {}
                public void onRmsChanged(float v) {}
                public void onBufferReceived(byte[] b) {}
                public void onEndOfSpeech() {}
                public void onPartialResults(Bundle b) {}
                public void onEvent(int t, Bundle b) {}
            });
        }
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-IN");
        recognizer.startListening(i);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        if (code == 7 && res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED) listen();
        else js("onSpeech('')");
    }

    // ---- the bridge the pages call -------------------------------------------------------------
    class Bridge {
        @JavascriptInterface public String last() { return prefs.getString("url", ""); }
        @JavascriptInterface public String gateway() {
            try {
                WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                int g = wm.getDhcpInfo().gateway;
                if (g == 0) return "";
                return (g & 255) + "." + ((g >> 8) & 255) + "." + ((g >> 16) & 255) + "." + ((g >> 24) & 255);
            } catch (Exception e) { return ""; }
        }
        @JavascriptInterface public void discover() { ui.post(new Runnable() { public void run() { startDiscovery(); } }); }
        @JavascriptInterface public void open(final String url) {
            if (!url.startsWith("http://") && !url.startsWith("https://")) return;
            prefs.edit().putString("url", url).apply();
            ui.post(new Runnable() { public void run() { stopDiscovery(); web.loadUrl(url); } });
        }
        @JavascriptInterface public void home() { ui.post(new Runnable() { public void run() { web.loadUrl(FINDER + "?again=1"); } }); }
        @JavascriptInterface public void listen() { ui.post(new Runnable() { public void run() { MainActivity.this.listen(); } }); }
        @JavascriptInterface public String version() { return "1.0 (Android " + Build.VERSION.RELEASE + ")"; }
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        stopDiscovery();
        if (recognizer != null) recognizer.destroy();
        super.onDestroy();
    }
}
