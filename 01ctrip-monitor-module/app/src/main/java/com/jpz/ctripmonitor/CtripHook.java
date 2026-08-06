package com.jpz.ctripmonitor;

import android.content.ContentValues;
import android.app.Application;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.webkit.WebView;

import java.io.FilterInputStream;
import java.io.FilterOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketAddress;
import java.nio.ByteBuffer;
import java.nio.charset.Charset;
import java.text.SimpleDateFormat;
import java.util.zip.GZIPInputStream;
import java.util.zip.Inflater;
import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.regex.Pattern;

import javax.crypto.Cipher;

import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

public final class CtripHook implements IXposedHookLoadPackage {
    private static final String TAG = "CtripMonitor";
    private static final String BUILD_MARKER = "single-final-json-v14";
    private static final int LOG_LIMIT = 4000;
    private static final int BODY_LOG_CHUNK = 1200;
    private static final long HTTP_BODY_LIMIT = 1024L * 1024L;
    private static final int CRONET_BODY_LIMIT = 1024 * 1024;
    private static final int TCP_STREAM_DUMP_LIMIT = 1024 * 1024;
    private static final int TCP_HEX_CHUNK = 768;
    private static final int DECODE_HEX_LIMIT = 256;
    private static final int DECODE_TEXT_LIMIT = 64 * 1024;
    private static final int HOTEL_FILE_NAME_LIMIT = 120;
    private static final int MAX_DECODE_CANDIDATE_LOGS = 120;
    private static final int MAX_TARGET_DECODE_LOGS = 2000;
    private static final int PREF_VALUE_LIMIT = 800;
    private static final long DUPLICATE_LOG_WINDOW_MS = 10_000L;
    private static final Charset UTF_8 = Charset.forName("UTF-8");
    private static final Set<ClassLoader> INSTALLED_LOADERS = Collections.newSetFromMap(
            new IdentityHashMap<ClassLoader, Boolean>());
    private static final Set<Class<?>> HOOKED_CRONET_CALLBACKS = Collections.newSetFromMap(
            new IdentityHashMap<Class<?>, Boolean>());
    private static final Set<Class<?>> HOOKED_PROTOBUF_CLASSES = Collections.newSetFromMap(
            new IdentityHashMap<Class<?>, Boolean>());
    private static final Set<String> HOOKED_REACT_BRIDGE_METHODS = new HashSet<String>();
    private static final Map<Object, String> CRONET_URLS = Collections.synchronizedMap(
            new WeakHashMap<Object, String>());
    private static final Map<Object, StringBuilder> CRONET_BODIES = Collections.synchronizedMap(
            new WeakHashMap<Object, StringBuilder>());
    private static final Map<Socket, String> SOCKET_ENDPOINTS = Collections.synchronizedMap(
            new WeakHashMap<Socket, String>());
    private static final Map<String, Integer> SAVED_HOTEL_BODY_LENGTHS = new LinkedHashMap<String, Integer>() {
        @Override
        protected boolean removeEldestEntry(Map.Entry<String, Integer> eldest) {
            return size() > 128;
        }
    };
    private static String lastHotelId = "";
    private static String lastHotelName = "hotel";
    private static String lastCheckInDate = "";
    private static final Map<String, Long> RECENT_LOGS = new LinkedHashMap<String, Long>() {
        @Override
        protected boolean removeEldestEntry(Map.Entry<String, Long> eldest) {
            return size() > 256;
        }
    };
    private static boolean webViewHooksInstalled;
    private static boolean activityHooksInstalled;
    private static boolean sharedPreferencesHooksInstalled;
    private static boolean classLoaderHooksInstalled;
    private static boolean socketHooksInstalled;
    private static boolean codecHooksInstalled;
    private static boolean jsonHooksInstalled;
    private static boolean base64HooksInstalled;
    private static Context appContext;
    private static int decodeCandidateLogs;
    private static int targetDecodeLogs;
    private static final Pattern[] SENSITIVE_QUERY_PATTERNS = new Pattern[]{
            Pattern.compile("(?i)(authorization|cookie|token|session|password|passwd|pwd|secret|key|ticket|sign|signature|clientid|client_id|deviceid|device_id|guid|gaid|oaid|vaid|aaid|androidid|imei|imsi|mac|utdid)=([^&\\s]+)"),
            Pattern.compile("(?i)(phone|mobile|tel|idcard|identity|certificate|passenger|email)=([^&\\s]+)")
    };
    private static final Pattern[] SENSITIVE_JSON_PATTERNS = new Pattern[]{
            Pattern.compile("(?i)(\"(?:authorization|cookie|token|session|password|passwd|pwd|secret|key|ticket|sign|signature|clientid|client_id|deviceid|device_id|guid|gaid|oaid|vaid|aaid|androidid|imei|imsi|mac|utdid)\"\\s*:\\s*\")([^\"]+)\""),
            Pattern.compile("(?i)(\"(?:phone|mobile|tel|idcard|identity|certificate|passenger|email)\"\\s*:\\s*\")([^\"]+)\""),
    };
    private static final Pattern[] SENSITIVE_STANDALONE_PATTERNS = new Pattern[]{
            Pattern.compile("\\b1[3-9]\\d{9}\\b"),
            Pattern.compile("\\b\\d{15}(?:\\d{2}[0-9Xx])?\\b")
    };

    // Verify the SIT build package with: aapt dump badging target.apk
    private static final Set<String> TARGET_PACKAGES = new HashSet<>(Arrays.asList(
            "ctrip.android.view"
    ));

    @Override
    public void handleLoadPackage(XC_LoadPackage.LoadPackageParam lpparam) {
        if (!TARGET_PACKAGES.contains(lpparam.packageName)) {
            return;
        }

        log("loaded package=" + lpparam.packageName + " process=" + lpparam.processName);

        XposedHelpers.findAndHookMethod(
                Application.class,
                "attach",
                Context.class,
                new XC_MethodHook() {
                    @Override
                    protected void afterHookedMethod(MethodHookParam param) {
                        Context context = (Context) param.args[0];
                        appContext = context.getApplicationContext();
                        ClassLoader loader = context.getClassLoader();
                        if (!markInstalled(loader)) {
                            return;
                        }
                        log("classLoader ready process=" + lpparam.processName + " build=" + BUILD_MARKER);
                        installGsonHooks(loader);
                        installOkHttpHooks(loader);
                        installCronetHooks(loader);
                        installClassLoaderHooks(loader);
                        installSocketHooks();
                        installCodecHooks(loader);
                        installTargetDecodeHooks(loader);
                        installJsonHooks(loader);
                        installBase64Hooks();
                        installReactBridgeHooks(loader);
                        installProtobufHooks(loader);
                        installWebViewHooks();
                        installActivityHooks();
                        installSharedPreferencesHooks(loader);
                    }
                });
    }

    private static boolean markInstalled(ClassLoader loader) {
        synchronized (INSTALLED_LOADERS) {
            if (INSTALLED_LOADERS.contains(loader)) {
                return false;
            }
            INSTALLED_LOADERS.add(loader);
            return true;
        }
    }

    private static void installGsonHooks(ClassLoader loader) {
        try {
            Class<?> gson = XposedHelpers.findClass("com.google.gson.Gson", loader);

            XposedBridge.hookAllMethods(gson, "toJson", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    logValue("Gson.toJson", param.getResult());
                }
            });

            XposedBridge.hookAllMethods(gson, "fromJson", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    if (param.args.length > 0) {
                        logValue("Gson.fromJson input", param.args[0]);
                    }
                }
            });

            log("Gson hooks installed");
        } catch (Throwable error) {
            log("Gson unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void installOkHttpHooks(ClassLoader loader) {
        try {
            Class<?> requestBuilder = XposedHelpers.findClass(
                    "okhttp3.Request$Builder", loader);

            XposedBridge.hookAllMethods(requestBuilder, "build", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    Object request = param.getResult();
                    if (request == null) {
                        return;
                    }

                    Object method = XposedHelpers.callMethod(request, "method");
                    Object url = XposedHelpers.callMethod(request, "url");
                    logHttp(method, url);
                }
            });

            Class<?> responseBuilder = XposedHelpers.findClass(
                    "okhttp3.Response$Builder", loader);

            XposedBridge.hookAllMethods(responseBuilder, "build", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    logHttpResponse(param.getResult());
                }
            });

            log("OkHttp hooks installed");
        } catch (Throwable error) {
            log("OkHttp unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void installSocketHooks() {
        synchronized (CtripHook.class) {
            if (socketHooksInstalled) {
                return;
            }
            socketHooksInstalled = true;
        }

        try {
            XposedBridge.hookAllMethods(Socket.class, "connect", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    if (!(param.thisObject instanceof Socket)) {
                        return;
                    }
                    Socket socket = (Socket) param.thisObject;
                    String endpoint = describeSocket(socket);
                    if (!shouldMonitorTcpEndpoint(endpoint)) {
                        return;
                    }
                    SOCKET_ENDPOINTS.put(socket, endpoint);
                    logValueOnce("TCP connect", endpoint);
                }
            });

            XposedBridge.hookAllMethods(Socket.class, "getInputStream", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    if (!(param.thisObject instanceof Socket) || !(param.getResult() instanceof InputStream)) {
                        return;
                    }
                    Socket socket = (Socket) param.thisObject;
                    String endpoint = getSocketEndpoint(socket);
                    if (!shouldMonitorTcpEndpoint(endpoint)) {
                        return;
                    }
                    InputStream input = (InputStream) param.getResult();
                    if (!(input instanceof MonitoredInputStream)) {
                        param.setResult(new MonitoredInputStream(input, endpoint));
                    }
                }
            });

            XposedBridge.hookAllMethods(Socket.class, "getOutputStream", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    if (!(param.thisObject instanceof Socket) || !(param.getResult() instanceof OutputStream)) {
                        return;
                    }
                    Socket socket = (Socket) param.thisObject;
                    String endpoint = getSocketEndpoint(socket);
                    if (!shouldMonitorTcpEndpoint(endpoint)) {
                        return;
                    }
                    OutputStream output = (OutputStream) param.getResult();
                    if (!(output instanceof MonitoredOutputStream)) {
                        param.setResult(new MonitoredOutputStream(output, endpoint));
                    }
                }
            });

            log("Socket hooks installed");
        } catch (Throwable error) {
            log("Socket hooks unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void installCodecHooks(ClassLoader loader) {
        synchronized (CtripHook.class) {
            if (codecHooksInstalled) {
                return;
            }
            codecHooksInstalled = true;
        }

        try {
            XposedBridge.hookAllMethods(Cipher.class, "doFinal", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    String algorithm = callStringMethod(param.thisObject, "getAlgorithm");
                    logCipherResult("Cipher.doFinal " + algorithm, param);
                }
            });
            log("Cipher hooks installed");
        } catch (Throwable error) {
            log("Cipher hooks unavailable: " + error.getClass().getSimpleName());
        }

        try {
            XposedBridge.hookAllMethods(Inflater.class, "inflate", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    if (!(param.getResult() instanceof Number) || param.args.length == 0
                            || !(param.args[0] instanceof byte[])) {
                        return;
                    }
                    int count = ((Number) param.getResult()).intValue();
                    if (count <= 0) {
                        return;
                    }
                    int offset = param.args.length > 1 && param.args[1] instanceof Integer
                            ? ((Integer) param.args[1]).intValue() : 0;
                    logDecodedBytes("Inflater.inflate", (byte[]) param.args[0], offset, count);
                }
            });
            log("Inflater hooks installed");
        } catch (Throwable error) {
            log("Inflater hooks unavailable: " + error.getClass().getSimpleName());
        }

        try {
            XposedBridge.hookAllMethods(GZIPInputStream.class, "read", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    if (!(param.getResult() instanceof Number) || param.args.length == 0
                            || !(param.args[0] instanceof byte[])) {
                        return;
                    }
                    int count = ((Number) param.getResult()).intValue();
                    if (count <= 0) {
                        return;
                    }
                    int offset = param.args.length > 1 && param.args[1] instanceof Integer
                            ? ((Integer) param.args[1]).intValue() : 0;
                    logDecodedBytes("GZIPInputStream.read", (byte[]) param.args[0], offset, count);
                }
            });
            log("GZIP hooks installed");
        } catch (Throwable error) {
            log("GZIP hooks unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void installTargetDecodeHooks(ClassLoader loader) {
        hookTargetMethod(loader, "J", "callback");
        hookTargetMethod(loader, "y3.a", "a");
        hookTargetMethod(loader, "d4.d", "d");
        hookTargetMethod(loader, "d4.d", "q");
        hookTargetMethod(loader, "d4.h", "run");
        log("Target decode hooks requested");
    }

    private static void hookTargetMethod(ClassLoader loader, String className, String methodName) {
        try {
            Class<?> target = XposedHelpers.findClass(className, loader);
            XposedBridge.hookAllMethods(target, methodName, new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    logTargetMethod("before", param);
                }

                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    logTargetMethod("after", param);
                }
            });
            log("Target hook installed " + className + "." + methodName);
        } catch (Throwable error) {
            log("Target hook unavailable " + className + "." + methodName + ": "
                    + error.getClass().getSimpleName());
        }
    }

    private static void logTargetMethod(String phase, XC_MethodHook.MethodHookParam param) {
        String method = stackSummary();
        if (shouldSkipTargetMethod(method, param)) {
            return;
        }
        if (!allowTargetDecodeLog()) {
            return;
        }
        log("TARGET " + phase + " stack=" + method + " this=" + describeTargetValue(param.thisObject));
        if (param.args != null) {
            for (int i = 0; i < param.args.length; i++) {
                logTargetValue("TARGET " + phase + " arg" + i + " stack=" + method, param.args[i]);
            }
        }
        if ("after".equals(phase)) {
            logTargetValue("TARGET result stack=" + method, param.getResult());
        }
    }

    private static boolean shouldSkipTargetMethod(String stack, XC_MethodHook.MethodHookParam param) {
        String lower = (stack == null ? "" : stack).toLowerCase(Locale.US);
        StringBuilder descriptor = new StringBuilder(lower);
        appendTargetDescriptor(descriptor, param.thisObject);
        if (param.args != null) {
            for (Object arg : param.args) {
                appendTargetDescriptor(descriptor, arg);
            }
        }
        String text = descriptor.toString();
        if (isBusinessText(text)) {
            return false;
        }
        return text.contains("com.ctrip.ubt")
                || text.contains("mobdata")
                || text.contains("d4.d.")
                || text.contains("d4.h.")
                || text.contains("y3.a.")
                || text.contains("licensecheckerplatformandroid")
                || text.contains("hotelincrementfileutils")
                || text.contains("flightcitydatasession");
    }

    private static void appendTargetDescriptor(StringBuilder builder, Object value) {
        if (value == null) {
            return;
        }
        builder.append(' ').append(value.getClass().getName().toLowerCase(Locale.US));
        if (value instanceof String) {
            builder.append(' ').append(((String) value).toLowerCase(Locale.US));
        }
    }

    private static boolean allowTargetDecodeLog() {
        synchronized (CtripHook.class) {
            if (targetDecodeLogs >= MAX_TARGET_DECODE_LOGS) {
                return false;
            }
            targetDecodeLogs++;
            return true;
        }
    }

    private static void installJsonHooks(ClassLoader loader) {
        synchronized (CtripHook.class) {
            if (jsonHooksInstalled) {
                return;
            }
            jsonHooksInstalled = true;
        }

        hookJsonClass("org.json.JSONObject", loader);
        hookJsonClass("org.json.JSONArray", loader);
        hookFastJson(loader);
        log("JSON hooks requested");
    }

    private static void hookJsonClass(String className, ClassLoader loader) {
        try {
            Class<?> jsonClass = XposedHelpers.findClass(className, loader);
            XposedBridge.hookAllConstructors(jsonClass, new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    if (param.args.length > 0 && param.args[0] instanceof String) {
                        logBusinessText("JSON.<init>", param.args[0]);
                    }
                }
            });
            XposedBridge.hookAllMethods(jsonClass, "toString", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    logBusinessText("JSON.toString " + param.thisObject.getClass().getName(),
                            param.getResult());
                }
            });
            log("JSON hook installed " + className);
        } catch (Throwable error) {
            log("JSON hook unavailable " + className + ": " + error.getClass().getSimpleName());
        }
    }

    private static void hookFastJson(ClassLoader loader) {
        try {
            Class<?> json = XposedHelpers.findClass("com.alibaba.fastjson.JSON", loader);
            hookStaticJsonMethod(json, "parse");
            hookStaticJsonMethod(json, "parseObject");
            hookStaticJsonMethod(json, "parseArray");
            hookStaticJsonMethod(json, "toJSONString");
            log("fastjson hooks installed");
        } catch (Throwable error) {
            log("fastjson unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void hookStaticJsonMethod(Class<?> json, final String methodName) {
        XposedBridge.hookAllMethods(json, methodName, new XC_MethodHook() {
            @Override
            protected void beforeHookedMethod(MethodHookParam param) {
                if (param.args != null && param.args.length > 0) {
                    logBusinessText("fastjson." + methodName + " input", param.args[0]);
                }
            }

            @Override
            protected void afterHookedMethod(MethodHookParam param) {
                logBusinessText("fastjson." + methodName + " result", param.getResult());
            }
        });
    }

    private static void installBase64Hooks() {
        synchronized (CtripHook.class) {
            if (base64HooksInstalled) {
                return;
            }
            base64HooksInstalled = true;
        }

        try {
            XposedBridge.hookAllMethods(android.util.Base64.class, "decode", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    if (param.getResult() instanceof byte[]) {
                        logDecodedBytes("Base64.decode", (byte[]) param.getResult(), 0,
                                ((byte[]) param.getResult()).length);
                    }
                }
            });
            log("Base64 hooks installed");
        } catch (Throwable error) {
            log("Base64 hooks unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void installReactBridgeHooks(ClassLoader loader) {
        hookReactBridgeClass(loader, "com.facebook.react.bridge.Callback", "invoke");
        hookReactBridgeClass(loader, "com.facebook.react.bridge.Promise", "resolve");
        hookReactBridgeClass(loader, "com.facebook.react.bridge.Promise", "reject");
        hookReactBridgeClass(loader, "com.facebook.react.bridge.WritableMap", "putString");
        hookReactBridgeClass(loader, "com.facebook.react.bridge.WritableMap", "putMap");
        hookReactBridgeClass(loader, "com.facebook.react.bridge.WritableMap", "putArray");
        hookReactBridgeClass(loader, "com.facebook.react.bridge.ReadableMap", "toHashMap");
        hookReactBridgeClass(loader, "com.facebook.react.bridge.ReadableArray", "toArrayList");
        log("React bridge hooks requested");
    }

    private static void hookReactBridgeClass(ClassLoader loader, String className, final String methodName) {
        try {
            Class<?> target = XposedHelpers.findClass(className, loader);
            maybeHookReactBridgeClass(target, methodName);
        } catch (Throwable error) {
            log("React bridge hook unavailable " + className + "." + methodName + ": "
                    + error.getClass().getSimpleName());
        }
    }

    private static void maybeHookReactBridgeClass(Class<?> candidate, final String methodName) {
        if (candidate == null || methodName == null) {
            return;
        }
        String className = candidate.getName();
        if (!className.startsWith("com.facebook.react.bridge.") && !implementsReactBridgeClass(candidate)) {
            return;
        }
        String key = className + "#" + methodName;
        synchronized (HOOKED_REACT_BRIDGE_METHODS) {
            if (HOOKED_REACT_BRIDGE_METHODS.contains(key)) {
                return;
            }
            HOOKED_REACT_BRIDGE_METHODS.add(key);
        }
        try {
            XposedBridge.hookAllMethods(candidate, methodName, new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    if (param.args != null) {
                        for (int i = 0; i < param.args.length; i++) {
                            logBusinessText("ReactBridge." + methodName + " arg" + i, param.args[i]);
                        }
                    }
                }

                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    logBusinessText("ReactBridge." + methodName + " result", param.getResult());
                }
            });
            log("React bridge hook installed " + key);
        } catch (Throwable error) {
            log("React bridge hook failed " + key + ": " + error.getClass().getSimpleName());
        }
    }

    private static void maybeHookLoadedReactBridgeClass(Class<?> candidate) {
        if (candidate == null || !implementsReactBridgeClass(candidate)) {
            return;
        }
        maybeHookReactBridgeClass(candidate, "invoke");
        maybeHookReactBridgeClass(candidate, "resolve");
        maybeHookReactBridgeClass(candidate, "reject");
        maybeHookReactBridgeClass(candidate, "putString");
        maybeHookReactBridgeClass(candidate, "putMap");
        maybeHookReactBridgeClass(candidate, "putArray");
        maybeHookReactBridgeClass(candidate, "toHashMap");
        maybeHookReactBridgeClass(candidate, "toArrayList");
    }

    private static boolean implementsReactBridgeClass(Class<?> candidate) {
        for (Class<?> current = candidate; current != null; current = current.getSuperclass()) {
            if (isReactBridgeName(current.getName())) {
                return true;
            }
            Class<?>[] interfaces = current.getInterfaces();
            for (Class<?> iface : interfaces) {
                if (isReactBridgeName(iface.getName())) {
                    return true;
                }
            }
        }
        return false;
    }

    private static boolean isReactBridgeName(String name) {
        return "com.facebook.react.bridge.Callback".equals(name)
                || "com.facebook.react.bridge.Promise".equals(name)
                || "com.facebook.react.bridge.WritableMap".equals(name)
                || "com.facebook.react.bridge.ReadableMap".equals(name)
                || "com.facebook.react.bridge.WritableArray".equals(name)
                || "com.facebook.react.bridge.ReadableArray".equals(name);
    }

    private static void logBusinessText(String source, Object value) {
        if (value == null) {
            return;
        }
        String text = safeToString(value);
        if (!isBusinessText(text) && !isBusinessText(value.getClass().getName())) {
            return;
        }
        saveHotelDetailBody(source, text);
        logBodyChunks(source + " stack=" + stackSummary(), text);
    }

    private static boolean isBusinessText(String text) {
        if (text == null || text.length() == 0) {
            return false;
        }
        String lower = text.toLowerCase(Locale.US);
        return lower.contains("hotel")
                || lower.contains("htl_")
                || lower.contains("masterhotelid")
                || lower.contains("getdetailadditionalinfo")
                || lower.contains("gethotelroomlistinland")
                || lower.contains("hotel_inland_detail")
                || lower.contains("rn_xtaro_hotel_detail")
                || text.contains("\u9152\u5e97")
                || text.contains("\u5168\u5b63");
    }

    private static void logTargetValue(String source, Object value) {
        if (value == null) {
            logValueOnce(source, "null");
            return;
        }
        if (value instanceof byte[]) {
            byte[] bytes = (byte[]) value;
            logDecodedBytes(source + " byte[]", bytes, 0, bytes.length);
            return;
        }
        if (value instanceof ByteBuffer) {
            ByteBuffer duplicate = ((ByteBuffer) value).asReadOnlyBuffer();
            int length = duplicate.remaining();
            byte[] bytes = new byte[Math.min(length, DECODE_TEXT_LIMIT)];
            duplicate.get(bytes);
            logDecodedBytes(source + " ByteBuffer", bytes, 0, bytes.length);
            return;
        }
        String text = safeToString(value);
        if (shouldLogDecodedText(text) || shouldLogTargetClass(value.getClass().getName())) {
            logBodyChunks(source + " " + value.getClass().getName(), text);
        } else {
            logValueOnce(source, describeTargetValue(value));
        }
    }

    private static boolean shouldLogTargetClass(String className) {
        if (className == null) {
            return false;
        }
        String lower = className.toLowerCase(Locale.US);
        return lower.contains("hotel")
                || lower.contains("room")
                || lower.contains("detail")
                || lower.contains("response")
                || lower.contains("result")
                || lower.contains("model")
                || lower.contains("json")
                || lower.startsWith("y3.")
                || lower.startsWith("d4.");
    }

    private static String describeTargetValue(Object value) {
        if (value == null) {
            return "null";
        }
        if (value instanceof byte[]) {
            byte[] bytes = (byte[]) value;
            return "byte[" + bytes.length + "] hex_head="
                    + toHex(bytes, 0, Math.min(bytes.length, DECODE_HEX_LIMIT))
                    + " ascii_head=" + toPrintableAscii(bytes, 0, Math.min(bytes.length, DECODE_HEX_LIMIT));
        }
        if (value instanceof ByteBuffer) {
            ByteBuffer duplicate = ((ByteBuffer) value).asReadOnlyBuffer();
            int length = duplicate.remaining();
            byte[] bytes = new byte[Math.min(length, DECODE_HEX_LIMIT)];
            duplicate.get(bytes);
            return "ByteBuffer[" + length + "] hex_head=" + toHex(bytes, 0, bytes.length)
                    + " ascii_head=" + toPrintableAscii(bytes, 0, bytes.length);
        }
        String text = safeToString(value);
        return value.getClass().getName() + " " + truncate(text);
    }

    private static void logCipherResult(String source, XC_MethodHook.MethodHookParam param) {
        if (param.getResult() instanceof byte[]) {
            byte[] result = (byte[]) param.getResult();
            logDecodedBytes(source, result, 0, result.length);
            return;
        }
        if (!(param.getResult() instanceof Number)) {
            return;
        }
        int count = ((Number) param.getResult()).intValue();
        if (count <= 0) {
            return;
        }
        for (int i = param.args.length - 1; i >= 0; i--) {
            if (!(param.args[i] instanceof byte[])) {
                continue;
            }
            int offset = 0;
            if (i + 1 < param.args.length && param.args[i + 1] instanceof Integer) {
                offset = ((Integer) param.args[i + 1]).intValue();
            }
            byte[] output = (byte[]) param.args[i];
            if (offset >= 0 && offset + count <= output.length) {
                logDecodedBytes(source, output, offset, count);
                return;
            }
        }
    }

    private static void installProtobufHooks(ClassLoader loader) {
        try {
            Class<?> parser = XposedHelpers.findClass("com.google.protobuf.Parser", loader);
            maybeHookProtobufParserClass(parser, parser);

            Class<?> abstractParser = XposedHelpers.findClass("com.google.protobuf.AbstractParser", loader);
            maybeHookProtobufParserClass(abstractParser, parser);

            log("Protobuf hooks installed");
        } catch (Throwable error) {
            log("Protobuf unavailable now: " + error.getClass().getSimpleName());
        }
    }

    private static void installCronetHooks(ClassLoader loader) {
        try {
            Class<?> callback = XposedHelpers.findClass("org.chromium.net.UrlRequest$Callback", loader);
            maybeHookCronetCallbackClass(callback);
            log("Cronet hooks installed");
        } catch (Throwable error) {
            log("Cronet unavailable now: " + error.getClass().getSimpleName());
        }
    }

    private static void installClassLoaderHooks(final ClassLoader targetLoader) {
        synchronized (CtripHook.class) {
            if (classLoaderHooksInstalled) {
                return;
            }
            classLoaderHooksInstalled = true;
        }

        try {
            XposedBridge.hookAllMethods(ClassLoader.class, "loadClass", new XC_MethodHook() {
                @Override
                protected void afterHookedMethod(MethodHookParam param) {
                    if (param.getResult() == null) {
                        return;
                    }
                    Class<?> loaded = (Class<?>) param.getResult();
                    if (loaded.getClassLoader() != targetLoader) {
                        return;
                    }
                    maybeHookCronetCallbackClass(loaded);
                    maybeHookLoadedProtobufClass(loaded, targetLoader);
                    maybeHookLoadedReactBridgeClass(loaded);
                }
            });
            log("ClassLoader hooks installed");
        } catch (Throwable error) {
            log("ClassLoader hooks unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void maybeHookLoadedProtobufClass(Class<?> candidate, ClassLoader loader) {
        String name = candidate.getName();
        if (!name.contains("protobuf") && !name.contains("proto")) {
            return;
        }
        try {
            Class<?> parser = XposedHelpers.findClass("com.google.protobuf.Parser", loader);
            maybeHookProtobufParserClass(candidate, parser);
        } catch (Throwable ignored) {
        }
    }

    private static void maybeHookProtobufParserClass(Class<?> candidate, Class<?> parserClass) {
        if (candidate == null || parserClass == null || !parserClass.isAssignableFrom(candidate)) {
            return;
        }
        synchronized (HOOKED_PROTOBUF_CLASSES) {
            if (HOOKED_PROTOBUF_CLASSES.contains(candidate)) {
                return;
            }
            HOOKED_PROTOBUF_CLASSES.add(candidate);
        }

        XposedBridge.hookAllMethods(candidate, "parseFrom", new XC_MethodHook() {
            @Override
            protected void afterHookedMethod(MethodHookParam param) {
                logParsedObject("PROTOBUF parseFrom", param.getResult());
            }
        });

        XposedBridge.hookAllMethods(candidate, "parsePartialFrom", new XC_MethodHook() {
            @Override
            protected void afterHookedMethod(MethodHookParam param) {
                logParsedObject("PROTOBUF parsePartialFrom", param.getResult());
            }
        });

        log("Protobuf parser hook installed " + candidate.getName());
    }

    private static void maybeHookCronetCallbackClass(Class<?> candidate) {
        if (candidate == null || !isCronetCallbackClass(candidate)) {
            return;
        }
        synchronized (HOOKED_CRONET_CALLBACKS) {
            if (HOOKED_CRONET_CALLBACKS.contains(candidate)) {
                return;
            }
            HOOKED_CRONET_CALLBACKS.add(candidate);
        }

        XposedBridge.hookAllMethods(candidate, "onResponseStarted", new XC_MethodHook() {
            @Override
            protected void beforeHookedMethod(MethodHookParam param) {
                if (param.args.length < 2) {
                    return;
                }
                startCronetCapture(param.args[0], param.args[1]);
            }
        });

        XposedBridge.hookAllMethods(candidate, "onReadCompleted", new XC_MethodHook() {
            @Override
            protected void beforeHookedMethod(MethodHookParam param) {
                if (param.args.length < 3 || !(param.args[2] instanceof ByteBuffer)) {
                    return;
                }
                appendCronetBody(param.args[0], param.args[1], (ByteBuffer) param.args[2]);
            }
        });

        XposedBridge.hookAllMethods(candidate, "onSucceeded", new XC_MethodHook() {
            @Override
            protected void beforeHookedMethod(MethodHookParam param) {
                if (param.args.length < 2) {
                    return;
                }
                finishCronetCapture(param.args[0], param.args[1], "succeeded");
            }
        });

        XposedBridge.hookAllMethods(candidate, "onFailed", new XC_MethodHook() {
            @Override
            protected void beforeHookedMethod(MethodHookParam param) {
                if (param.args.length < 2) {
                    return;
                }
                finishCronetCapture(param.args[0], param.args[1], "failed");
            }
        });

        log("Cronet callback hook installed " + candidate.getName());
    }

    private static boolean isCronetCallbackClass(Class<?> candidate) {
        for (Class<?> current = candidate; current != null; current = current.getSuperclass()) {
            if ("org.chromium.net.UrlRequest$Callback".equals(current.getName())) {
                return true;
            }
        }
        return false;
    }

    private static void startCronetCapture(Object request, Object info) {
        String url = getCronetUrl(request, info);
        if (!shouldLogHttpBodyUrl(url)) {
            return;
        }
        CRONET_URLS.put(request, url);
        CRONET_BODIES.put(request, new StringBuilder());
        logValueOnce("CRONET responseStarted", normalizeUrlForLog(url));
    }

    private static void appendCronetBody(Object request, Object info, ByteBuffer buffer) {
        String url = CRONET_URLS.get(request);
        if (url == null) {
            url = getCronetUrl(request, info);
            if (!shouldLogHttpBodyUrl(url)) {
                return;
            }
            CRONET_URLS.put(request, url);
            CRONET_BODIES.put(request, new StringBuilder());
        }

        StringBuilder body = CRONET_BODIES.get(request);
        if (body == null || body.length() >= CRONET_BODY_LIMIT) {
            return;
        }

        ByteBuffer duplicate = buffer.asReadOnlyBuffer();
        int remaining = duplicate.remaining();
        if (remaining <= 0) {
            return;
        }
        int bytesToRead = Math.min(remaining, CRONET_BODY_LIMIT - body.length());
        byte[] bytes = new byte[bytesToRead];
        duplicate.get(bytes);
        body.append(new String(bytes, UTF_8));
    }

    private static void finishCronetCapture(Object request, Object info, String status) {
        String url = CRONET_URLS.remove(request);
        StringBuilder body = CRONET_BODIES.remove(request);
        if (url == null) {
            url = getCronetUrl(request, info);
        }
        if (!shouldLogHttpBodyUrl(url)) {
            return;
        }
        if (body == null) {
            logValueOnce("CRONET " + status, normalizeUrlForLog(url));
            return;
        }
        String source = "CRONET BODY " + status + " " + normalizeUrlForLog(url);
        logBodyChunks(source, body.toString());
    }

    private static String getCronetUrl(Object request, Object info) {
        String url = callStringMethod(info, "getUrl");
        if (url != null && !"null".equals(url)) {
            return url;
        }
        url = callStringMethod(request, "getUrl");
        if (url != null && !"null".equals(url)) {
            return url;
        }
        return safeToString(request);
    }

    private static String callStringMethod(Object target, String methodName) {
        if (target == null) {
            return null;
        }
        try {
            Object result = XposedHelpers.callMethod(target, methodName);
            return safeToString(result);
        } catch (Throwable ignored) {
            return null;
        }
    }

    private static String getSocketEndpoint(Socket socket) {
        String endpoint = SOCKET_ENDPOINTS.get(socket);
        if (endpoint != null) {
            return endpoint;
        }
        endpoint = describeSocket(socket);
        if (shouldMonitorTcpEndpoint(endpoint)) {
            SOCKET_ENDPOINTS.put(socket, endpoint);
        }
        return endpoint;
    }

    private static String describeSocket(Socket socket) {
        if (socket == null) {
            return "null";
        }
        try {
            SocketAddress remote = socket.getRemoteSocketAddress();
            if (remote instanceof InetSocketAddress) {
                InetSocketAddress address = (InetSocketAddress) remote;
                String host = address.getHostString();
                String ip = address.getAddress() == null ? "" : address.getAddress().getHostAddress();
                return host + "/" + ip + ":" + address.getPort();
            }
            if (remote != null) {
                return safeToString(remote);
            }
        } catch (Throwable ignored) {
        }
        return safeToString(socket);
    }

    private static boolean shouldMonitorTcpEndpoint(String endpoint) {
        if (endpoint == null || "null".equals(endpoint)) {
            return false;
        }
        String lower = endpoint.toLowerCase(Locale.US);
        if (lower.contains("127.0.0.1")
                || lower.contains("localhost")
                || lower.contains("/10.0.2.2:")
                || lower.contains("10.0.2.2:")
                || lower.contains("ma-adx.ctrip.com")
                || lower.contains(":443")) {
            return false;
        }
        return lower.contains("ctrip")
                || lower.contains("tripcdn")
                || lower.contains("mobubt")
                || lower.contains("211.95.54.14")
                || lower.contains("114.80.56.14")
                || lower.contains("117.186.233.21")
                || lower.contains("162.14.")
                || lower.contains("220.196.164.4")
                || lower.contains("180.163.115.9")
                || lower.contains("117.131.27.20")
                || lower.contains(":80")
                || lower.contains(":443");
    }

    private static void logTcpBytes(String direction, String endpoint, byte[] data, int offset, int length, int sequence) {
        if (length <= 0 || data == null) {
            return;
        }
        int remaining = Math.min(length, TCP_STREAM_DUMP_LIMIT);
        int chunks = (remaining + TCP_HEX_CHUNK - 1) / TCP_HEX_CHUNK;
        String cleanEndpoint = sanitize(endpoint);
        for (int i = 0; i < chunks; i++) {
            int chunkOffset = offset + i * TCP_HEX_CHUNK;
            int chunkLength = Math.min(TCP_HEX_CHUNK, remaining - i * TCP_HEX_CHUNK);
            String source = "TCP " + direction + " seq=" + sequence + " " + cleanEndpoint
                    + " len=" + length + " chunk " + (i + 1) + "/" + chunks;
            log(source + " hex=" + toHex(data, chunkOffset, chunkLength)
                    + " ascii=" + toPrintableAscii(data, chunkOffset, chunkLength));
        }
    }

    private static String toHex(byte[] data, int offset, int length) {
        char[] out = new char[length * 2];
        final char[] digits = "0123456789abcdef".toCharArray();
        for (int i = 0; i < length; i++) {
            int value = data[offset + i] & 0xFF;
            out[i * 2] = digits[value >>> 4];
            out[i * 2 + 1] = digits[value & 0x0F];
        }
        return new String(out);
    }

    private static String toPrintableAscii(byte[] data, int offset, int length) {
        int visibleLength = Math.min(length, 512);
        StringBuilder builder = new StringBuilder(visibleLength);
        for (int i = 0; i < visibleLength; i++) {
            int value = data[offset + i] & 0xFF;
            if (value >= 0x20 && value <= 0x7E) {
                builder.append((char) value);
            } else {
                builder.append('.');
            }
        }
        if (length > visibleLength) {
            builder.append("...[ascii-truncated]");
        }
        return sanitize(builder.toString());
    }

    private static void logDecodedBytes(String source, byte[] data, int offset, int length) {
        if (data == null || length <= 0 || offset < 0 || offset >= data.length) {
            return;
        }
        int safeLength = Math.min(length, data.length - offset);
        if (safeLength <= 0) {
            return;
        }

        String text = new String(data, offset, Math.min(safeLength, DECODE_TEXT_LIMIT), UTF_8);
        String ascii = toPrintableAscii(data, offset, Math.min(safeLength, DECODE_HEX_LIMIT));
        boolean interesting = shouldLogDecodedText(text) || shouldLogDecodedText(ascii);
        boolean candidate = interesting || shouldLogDecodeCandidate(source, data, offset, safeLength);
        if (!candidate) {
            return;
        }

        String key = source + ":" + safeLength + ":" + toHex(data, offset, Math.min(safeLength, 32));
        if (!markRecent(key)) {
            return;
        }

        log(source + " len=" + safeLength
                + " printable=" + printableRatio(data, offset, safeLength)
                + " hex_head=" + toHex(data, offset, Math.min(safeLength, DECODE_HEX_LIMIT))
                + " ascii_head=" + ascii
                + " stack=" + stackSummary());

        if (interesting) {
            logBodyChunks("DECODED BODY " + source, text);
        }
    }

    private static boolean shouldLogDecodeCandidate(String source, byte[] data, int offset, int length) {
        if (length < 64) {
            return false;
        }
        if (startsWithGzip(data, offset, length) || startsWithJson(data, offset, length)) {
            return true;
        }
        if (!source.startsWith("Cipher.doFinal") && printableRatioValue(data, offset, length) < 0.08) {
            return false;
        }
        synchronized (CtripHook.class) {
            if (decodeCandidateLogs >= MAX_DECODE_CANDIDATE_LOGS) {
                return false;
            }
            decodeCandidateLogs++;
            return true;
        }
    }

    private static boolean startsWithGzip(byte[] data, int offset, int length) {
        return length >= 2 && (data[offset] & 0xFF) == 0x1F && (data[offset + 1] & 0xFF) == 0x8B;
    }

    private static boolean startsWithJson(byte[] data, int offset, int length) {
        for (int i = 0; i < Math.min(length, 32); i++) {
            int value = data[offset + i] & 0xFF;
            if (value <= 0x20) {
                continue;
            }
            return value == '{' || value == '[';
        }
        return false;
    }

    private static void logParsedObject(String source, Object value) {
        if (value == null) {
            return;
        }
        String className = value.getClass().getName();
        String text = safeToString(value);
        boolean interesting = shouldLogDecodedText(className) || shouldLogDecodedText(text);
        if (!interesting && !className.toLowerCase(Locale.US).contains("hotel")) {
            return;
        }
        logBodyChunks(source + " " + className + " stack=" + stackSummary(), text);
    }

    private static boolean shouldLogDecodedText(String text) {
        if (text == null || text.length() == 0) {
            return false;
        }
        String lower = text.toLowerCase(Locale.US);
        return lower.contains("hotel")
                || lower.contains("detail")
                || lower.contains("masterhotelid")
                || lower.contains("rn_xtaro_hotel_detail")
                || text.contains("酒店")
                || text.contains("西安")
                || text.contains("全季");
    }

    private static String printableRatio(byte[] data, int offset, int length) {
        return String.format(Locale.US, "%.2f", printableRatioValue(data, offset, length));
    }

    private static double printableRatioValue(byte[] data, int offset, int length) {
        int sample = Math.min(length, 1024);
        if (sample <= 0) {
            return 0.0d;
        }
        int printable = 0;
        for (int i = 0; i < sample; i++) {
            int value = data[offset + i] & 0xFF;
            if ((value >= 0x20 && value <= 0x7E) || value == '\n' || value == '\r' || value == '\t') {
                printable++;
            }
        }
        return (double) printable / (double) sample;
    }

    private static String stackSummary() {
        StackTraceElement[] stack = new Throwable().getStackTrace();
        StringBuilder builder = new StringBuilder();
        int count = 0;
        for (StackTraceElement frame : stack) {
            String name = frame.getClassName();
            if (name.startsWith("com.jpz.ctripmonitor")
                    || name.startsWith("de.robv.android.xposed")
                    || name.startsWith("java.")
                    || name.startsWith("javax.")
                    || name.startsWith("android.")
                    || name.startsWith("dalvik.")) {
                continue;
            }
            if (count > 0) {
                builder.append(" <- ");
            }
            builder.append(name).append(".").append(frame.getMethodName()).append(":").append(frame.getLineNumber());
            count++;
            if (count >= 8) {
                break;
            }
        }
        return builder.length() == 0 ? "<no-app-frame>" : sanitize(builder.toString());
    }

    private static void installWebViewHooks() {
        synchronized (CtripHook.class) {
            if (webViewHooksInstalled) {
                return;
            }
            webViewHooksInstalled = true;
        }

        try {
            XposedHelpers.findAndHookMethod(
                    WebView.class,
                    "loadUrl",
                    String.class,
                    new XC_MethodHook() {
                        @Override
                        protected void beforeHookedMethod(MethodHookParam param) {
                            logUrl("WebView.loadUrl", param.args[0]);
                        }
                    });

            XposedHelpers.findAndHookMethod(
                    WebView.class,
                    "postUrl",
                    String.class,
                    byte[].class,
                    new XC_MethodHook() {
                        @Override
                        protected void beforeHookedMethod(MethodHookParam param) {
                            logUrl("WebView.postUrl", param.args[0]);
                        }
                    });

            XposedBridge.hookAllMethods(WebView.class, "loadDataWithBaseURL", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    logUrl("WebView.loadDataWithBaseURL baseUrl", param.args.length > 0 ? param.args[0] : null);
                }
            });

            XposedBridge.hookAllMethods(WebView.class, "evaluateJavascript", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    logValue("WebView.evaluateJavascript", param.args.length > 0 ? param.args[0] : null);
                }
            });

            log("WebView hooks installed");
        } catch (Throwable error) {
            log("WebView hooks unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void installActivityHooks() {
        synchronized (CtripHook.class) {
            if (activityHooksInstalled) {
                return;
            }
            activityHooksInstalled = true;
        }

        try {
            XposedBridge.hookAllMethods(Activity.class, "onCreate", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    Activity activity = (Activity) param.thisObject;
                    logActivityIntent("Activity.onCreate " + activity.getClass().getName(), activity.getIntent());
                    if (param.args.length > 0) {
                        logBundle("Activity.onCreate bundle", param.args[0]);
                    }
                }
            });

            XposedBridge.hookAllMethods(Activity.class, "onNewIntent", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    Activity activity = (Activity) param.thisObject;
                    logActivityIntent("Activity.onNewIntent " + activity.getClass().getName(),
                            param.args.length > 0 ? (Intent) param.args[0] : null);
                }
            });

            log("Activity hooks installed");
        } catch (Throwable error) {
            log("Activity hooks unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void installSharedPreferencesHooks(ClassLoader loader) {
        synchronized (CtripHook.class) {
            if (sharedPreferencesHooksInstalled) {
                return;
            }
            sharedPreferencesHooksInstalled = true;
        }

        try {
            Class<?> editor = XposedHelpers.findClass(
                    "android.app.SharedPreferencesImpl$EditorImpl", loader);

            XposedBridge.hookAllMethods(editor, "putString", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    logPreferenceValue("SharedPreferences.putString", param.args);
                }
            });

            XposedBridge.hookAllMethods(editor, "putBoolean", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    logPreferenceValue("SharedPreferences.putBoolean", param.args);
                }
            });

            XposedBridge.hookAllMethods(editor, "putInt", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    logPreferenceValue("SharedPreferences.putInt", param.args);
                }
            });

            XposedBridge.hookAllMethods(editor, "putLong", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    logPreferenceValue("SharedPreferences.putLong", param.args);
                }
            });

            XposedBridge.hookAllMethods(editor, "putFloat", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    logPreferenceValue("SharedPreferences.putFloat", param.args);
                }
            });

            XposedBridge.hookAllMethods(editor, "remove", new XC_MethodHook() {
                @Override
                protected void beforeHookedMethod(MethodHookParam param) {
                    if (param.args.length > 0 && shouldLogPreferenceKey(safeToString(param.args[0]), null)) {
                        logValueOnce("SharedPreferences.remove", param.args[0]);
                    }
                }
            });

            log("SharedPreferences hooks installed");
        } catch (Throwable error) {
            log("SharedPreferences hooks unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void logActivityIntent(String source, Intent intent) {
        if (intent == null) {
            log(source + ": null");
            return;
        }
        logValue(source, intent.toUri(Intent.URI_INTENT_SCHEME));
        logBundle(source + " extras", intent.getExtras());
    }

    private static void logBundle(String source, Object value) {
        if (!(value instanceof Bundle)) {
            return;
        }
        Bundle bundle = (Bundle) value;
        Set<String> keys = bundle.keySet();
        StringBuilder builder = new StringBuilder();
        builder.append("{");
        boolean first = true;
        for (String key : keys) {
            if (!first) {
                builder.append(", ");
            }
            first = false;
            Object item;
            try {
                item = bundle.get(key);
            } catch (Throwable error) {
                item = "<unreadable:" + error.getClass().getSimpleName() + ">";
            }
            builder.append(key).append("=").append(safeToString(item));
        }
        builder.append("}");
        logValue(source, builder.toString());
    }

    private static void logPreferenceValue(String source, Object[] args) {
        if (args.length < 2) {
            return;
        }
        String key = safeToString(args[0]);
        String value = safeToString(args[1]);
        if (!shouldLogPreferenceKey(key, value)) {
            return;
        }
        logValueOnce(source, key + "=" + truncateForPreference(value));
    }

    private static void logHttp(Object method, Object urlValue) {
        String url = safeToString(urlValue);
        if (!shouldLogHttpUrl(url)) {
            return;
        }
        logValueOnce("HTTP " + method, normalizeUrlForLog(url));
    }

    private static void logHttpResponse(Object response) {
        if (response == null) {
            return;
        }
        try {
            Object request = XposedHelpers.callMethod(response, "request");
            Object urlValue = request == null ? null : XposedHelpers.callMethod(request, "url");
            String url = safeToString(urlValue);
            if (!shouldLogHttpBodyUrl(url)) {
                return;
            }

            Object code = XposedHelpers.callMethod(response, "code");
            Object message = XposedHelpers.callMethod(response, "message");
            Object peekBody = XposedHelpers.callMethod(response, "peekBody", HTTP_BODY_LIMIT);
            String body = peekBody == null ? "null" : safeToString(XposedHelpers.callMethod(peekBody, "string"));
            logBodyChunks("HTTP BODY " + code + " " + message + " " + normalizeUrlForLog(url), body);
        } catch (Throwable error) {
            log("HTTP BODY unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void logUrl(String source, Object urlValue) {
        String url = safeToString(urlValue);
        if (!shouldLogWebUrl(url)) {
            return;
        }
        logValueOnce(source, normalizeUrlForLog(url));
    }

    private static void logValue(String source, Object value) {
        String text = truncate(sanitize(safeToString(value)));
        log(source + ": " + text);
    }

    private static void logValueOnce(String source, Object value) {
        String text = truncate(sanitize(safeToString(value)));
        if (markRecent(source + ":" + text)) {
            log(source + ": " + text);
        }
    }

    private static void logBodyChunks(String source, String value) {
        saveHotelDetailBody(source, value);
        String text = sanitize(value);
        int total = text.length();
        if (markRecent(source + ":" + Math.min(total, 256) + ":" + text.substring(0, Math.min(total, 256)))) {
            log(source + " length=" + total + (total >= HTTP_BODY_LIMIT ? " [peek-limit-reached]" : ""));
            if (total == 0) {
                log(source + " chunk 1/1: ");
                return;
            }
            int chunks = (total + BODY_LOG_CHUNK - 1) / BODY_LOG_CHUNK;
            for (int i = 0; i < chunks; i++) {
                int start = i * BODY_LOG_CHUNK;
                int end = Math.min(start + BODY_LOG_CHUNK, total);
                log(source + " chunk " + (i + 1) + "/" + chunks + ": " + text.substring(start, end));
            }
        }
    }

    private static void saveHotelDetailBody(String source, String body) {
        try {
            saveHotelDetailBodyInternal(source, body);
        } catch (Throwable error) {
            log("HOTEL BODY unexpected failure " + error.getClass().getName() + ": "
                    + error.getMessage() + " source=" + source
                    + " length=" + (body == null ? 0 : body.length()));
        }
    }

    private static void saveHotelDetailBodyInternal(String source, String body) {
        if (body == null) {
            return;
        }
        boolean hotelDetailBody = isHotelDetailBody(source, body);
        boolean priceClueBody = isPriceClueBody(source, body);
        if (!hotelDetailBody && !priceClueBody) {
            if (looksLikeHotelJson(body)) {
                log("HOTEL BODY skip not-detail source=" + source + " length=" + body.length());
            }
            return;
        }
        refreshAppContext();
        log("HOTEL BODY candidate source=" + source + " length=" + body.length());

        String hotelId = firstMatch(body,
                "\"(?:hotelId|masterHotelId|masterhotelid|HotelId|MasterHotelId)\"\\s*:\\s*\"?(\\d+)\"?",
                "(?i)hotelid=(\\d+)");
        if (hotelId.length() == 0) {
            if (priceClueBody && !hotelDetailBody && lastHotelId.length() == 0) {
                log("HOTEL BODY skip price clue without hotel context source=" + source
                        + " length=" + body.length());
                return;
            }
            hotelId = lastHotelId;
        }
        if (hotelId.length() == 0) {
            hotelId = "0";
        }

        String hotelName = firstMatch(body,
                "\"hotelName\"\\s*:\\s*\"([^\"]+)\"",
                "\"nameInfo\"\\s*:\\s*\\{\\s*\"name\"\\s*:\\s*\"([^\"]+)\"",
                "\"hotelBaseInfo\"[\\s\\S]{0,800}?\"name\"\\s*:\\s*\"([^\"]+)\"");
        if (hotelName.length() == 0) {
            hotelName = lastHotelName.length() == 0 ? "hotel" : lastHotelName;
        }

        String purpose = detectHotelBodyPurpose(source, body, hotelDetailBody, priceClueBody);
        String checkInDate = firstMatch(body,
                "\"(?:checkInDate|CheckInDate|checkIn|CheckIn)\"\\s*:\\s*\"([0-9\\-\\/]{8,10})\"",
                "\"(?:inday|atime)\"\\s*:\\s*\"?([0-9\\-\\/]{8,10})\"?");
        if (checkInDate.length() == 0) {
            checkInDate = lastCheckInDate.length() == 0 ? captureDate() : lastCheckInDate;
        }
        checkInDate = formatDateForFile(checkInDate);

        rememberHotelContext(hotelId, hotelName, checkInDate);
        if (!"\u6700\u7ec8".equals(purpose)) {
            log("HOTEL BODY skip auxiliary purpose=" + purpose + " source=" + source
                    + " length=" + body.length());
            return;
        }
        if (priceClueBody && !hotelDetailBody && "\u4ef7\u683c\u7ebf\u7d22".equals(purpose)) {
            purpose = purpose + "-" + shortHash(source + ":" + body);
        }

        String fileName;
        if ("\u6700\u7ec8".equals(purpose)) {
            fileName = sanitizeFileName(hotelId + "_" + hotelName + "_"
                    + checkInDate.replace("-", "")) + ".json";
        } else {
            fileName = sanitizeFileName(hotelId + "_" + hotelName + "_" + purpose + "_" + checkInDate)
                    + ".json";
        }
        String key = hotelId + "|" + hotelName + "|" + purpose + "|" + checkInDate;
        synchronized (SAVED_HOTEL_BODY_LENGTHS) {
            Integer savedLength = SAVED_HOTEL_BODY_LENGTHS.get(key);
            if (savedLength != null && savedLength.intValue() >= body.length()) {
                log("HOTEL BODY skip already saved file=" + fileName + " savedLength=" + savedLength
                        + " currentLength=" + body.length());
                return;
            }
        }
        log("HOTEL BODY file plan file=" + fileName + " hotelId=" + hotelId
                + " hotelName=" + hotelName + " purpose=" + purpose + " checkInDate=" + checkInDate
                + " appContext=" + (appContext == null ? "null" : appContext.getPackageName()));

        if (saveHotelDetailBodyDirectDownload(fileName, body, source)) {
            markHotelBodySaved(key, body.length());
            return;
        }

        if (appContext != null && saveHotelDetailBodyViaDownloadsMediaStore(fileName, body, source)) {
            markHotelBodySaved(key, body.length());
            return;
        }

        log("HOTEL BODY save failed download methods file=" + fileName + " length=" + body.length()
                + " source=" + source);
    }

    private static void markHotelBodySaved(String key, int length) {
        synchronized (SAVED_HOTEL_BODY_LENGTHS) {
            SAVED_HOTEL_BODY_LENGTHS.put(key, length);
        }
    }

    private static boolean saveHotelDetailBodyDirectDownload(String fileName, String body, String source) {
        File downloads = new File("/sdcard/Download");
        if (!downloads.exists() && !downloads.mkdirs()) {
            downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        }
        if (downloads == null || (!downloads.exists() && !downloads.mkdirs())) {
            log("HOTEL BODY save failed downloads unavailable "
                    + (downloads == null ? "null" : downloads.getAbsolutePath()));
            return false;
        }

        File out = new File(downloads, fileName);
        FileOutputStream output = null;
        try {
            output = new FileOutputStream(out, false);
            output.write(body.getBytes(UTF_8));
            output.flush();
            log("HOTEL BODY saved " + out.getAbsolutePath() + " length=" + body.length()
                    + " source=" + source);
            return true;
        } catch (Throwable error) {
            log("HOTEL BODY direct download save failed " + error.getClass().getSimpleName() + ": "
                    + error.getMessage() + " path=" + out.getAbsolutePath());
            return false;
        } finally {
            if (output != null) {
                try {
                    output.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static void refreshAppContext() {
        if (appContext != null) {
            return;
        }
        try {
            Class<?> activityThread = Class.forName("android.app.ActivityThread");
            Method currentApplication = activityThread.getDeclaredMethod("currentApplication");
            currentApplication.setAccessible(true);
            Object application = currentApplication.invoke(null);
            if (application instanceof Context) {
                appContext = ((Context) application).getApplicationContext();
                log("resolved appContext from ActivityThread.currentApplication");
            }
        } catch (Throwable ignored) {
        }
    }

    private static boolean saveHotelDetailBodyViaDownloadsMediaStore(
            String fileName, String body, String source) {
        Uri collection = MediaStore.Files.getContentUri("external");
        Uri uri = null;
        OutputStream output = null;
        try {
            appContext.getContentResolver().delete(collection,
                    MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                    new String[]{fileName});

            ContentValues values = new ContentValues();
            values.put(MediaStore.MediaColumns.DISPLAY_NAME, fileName);
            values.put(MediaStore.MediaColumns.MIME_TYPE, "application/json");
            values.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
            uri = appContext.getContentResolver().insert(collection, values);
            if (uri == null) {
                log("HOTEL BODY Downloads MediaStore insert returned null file=" + fileName);
                return false;
            }
            output = appContext.getContentResolver().openOutputStream(uri, "w");
            if (output == null) {
                log("HOTEL BODY Downloads MediaStore output null file=" + fileName);
                return false;
            }
            output.write(body.getBytes(UTF_8));
            output.flush();
            log("HOTEL BODY saved Downloads MediaStore Download/" + fileName + " uri=" + uri
                    + " length=" + body.length() + " source=" + source);
            return true;
        } catch (Throwable error) {
            log("HOTEL BODY Downloads MediaStore save failed " + error.getClass().getSimpleName()
                    + ": " + error.getMessage() + " file=" + fileName);
            if (uri != null) {
                try {
                    appContext.getContentResolver().delete(uri, null, null);
                } catch (Throwable ignored) {
                }
            }
            return false;
        } finally {
            if (output != null) {
                try {
                    output.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static boolean isHotelDetailBody(String source, String body) {
        if (body == null || body.length() < 256 || !body.startsWith("{")) {
            return false;
        }
        String lower = (source + " " + body).toLowerCase(Locale.US);
        if (!lower.contains("hotel")) {
            return false;
        }
        return lower.contains("gethoteldetailaggregate")
                || lower.contains("getdetailadditionalinfo")
                || lower.contains("gethotelroomlistinland")
                || lower.contains("gethotelroompopinfo")
                || (lower.contains("hotelid") && lower.contains("hotelname")
                && (lower.contains("checkindate") || lower.contains("roomname")
                || lower.contains("tripinfo") || lower.contains("roominfo")))
                || lower.contains("hotelbaseinfo")
                || lower.contains("hotelreservationtips")
                || lower.contains("hotelintroduction")
                || lower.contains("hotelfacility")
                || lower.contains("roomlayerinfolist")
                || lower.contains("baseroomlist")
                || lower.contains("roomlist")
                || lower.contains("commenttaglist");
    }

    private static boolean looksLikeHotelJson(String body) {
        if (body == null || body.length() < 256 || !body.startsWith("{")) {
            return false;
        }
        String lower = body.toLowerCase(Locale.US);
        return lower.contains("hotel")
                || lower.contains("masterhotelid")
                || lower.contains("roomid")
                || body.contains("\u9152\u5e97");
    }

    private static boolean isPriceClueBody(String source, String body) {
        if (body == null || body.length() < 128 || !body.startsWith("{")) {
            return false;
        }
        String lower = (source + " " + body).toLowerCase(Locale.US);
        boolean hasPriceSignal = lower.contains("displayprice")
                || lower.contains("saleprice")
                || lower.contains("roomprice")
                || lower.contains("priceinfo")
                || lower.contains("pricepayment")
                || lower.contains("customerprice")
                || lower.contains("guaranteeprice")
                || lower.contains("passprice")
                || lower.contains("amount")
                || lower.contains("cnyamount")
                || body.contains("\u00a5")
                || body.contains("\uffe5");
        if (!hasPriceSignal) {
            return false;
        }
        return lower.contains("hotel")
                || lower.contains("room")
                || lower.contains("reservation")
                || lower.contains("booking")
                || lower.contains("inland")
                || lower.contains("checkin")
                || lower.contains("ctrip");
    }

    private static String detectHotelBodyPurpose(
            String source, String body, boolean hotelDetailBody, boolean priceClueBody) {
        String lower = (source + " " + body).toLowerCase(Locale.US);
        if ((lower.contains("saleroommap") && lower.contains("physicroommap"))
                || (lower.contains("hotellistinfo") && lower.contains("minpriceroomtraceinfo")
                && lower.contains("priceinfo"))) {
            return "\u6700\u7ec8";
        }
        if (lower.contains("reservationpricepaymentinfo")
                || lower.contains("reservationbasicinfo")
                || lower.contains("hotel_inland_order")
                || lower.contains("passprice")) {
            return "\u4e0b\u5355\u4ef7\u683c";
        }
        if (lower.contains("roomlayerinfolist")) {
            return "\u623f\u578b\u8be6\u60c5";
        }
        if (lower.contains("cachepolicy") && lower.contains("\"body\"")
                && lower.contains("hotel_inland_detail")) {
            return "\u8bf7\u6c42\u5305\u88c5";
        }
        if (lower.contains("commenttaglist")
                || lower.contains("commentrating")
                || lower.contains("commentlist")
                || lower.contains("packagelist")) {
            return "\u70b9\u8bc4";
        }
        if (lower.contains("gethotelroomlistinland")
                || lower.contains("baseroomlist")
                || lower.contains("\"roomlist\"")) {
            return "\u623f\u578b\u5217\u8868";
        }
        if (lower.contains("hotelreservationtips")
                || lower.contains("hotelintroduction")
                || lower.contains("hotelfacility")
                || lower.contains("hotelpolicy")
                || lower.contains("questionandanswer")) {
            return "\u9152\u5e97\u8865\u5145";
        }
        if (priceClueBody && !hotelDetailBody) {
            return "\u4ef7\u683c\u7ebf\u7d22";
        }
        return "\u9152\u5e97\u8be6\u60c5";
    }

    private static void rememberHotelContext(String hotelId, String hotelName, String checkInDate) {
        if (hotelId == null || hotelId.length() == 0 || "0".equals(hotelId)) {
            return;
        }
        lastHotelId = hotelId;
        if (hotelName != null && hotelName.length() != 0 && !"hotel".equals(hotelName)) {
            lastHotelName = hotelName;
        }
        if (checkInDate != null && checkInDate.length() != 0) {
            lastCheckInDate = checkInDate;
        }
    }

    private static String shortHash(String value) {
        int hash = value == null ? 0 : value.hashCode();
        String hex = Integer.toHexString(hash);
        return hex.length() > 8 ? hex.substring(hex.length() - 8) : hex;
    }

    private static String formatDateForFile(String date) {
        if (date == null || date.length() == 0) {
            return captureDate();
        }
        String digits = date.replace("-", "").replace("/", "");
        if (digits.length() >= 8) {
            return digits.substring(0, 4) + "-" + digits.substring(4, 6) + "-" + digits.substring(6, 8);
        }
        return captureDate();
    }

    private static String captureDate() {
        try {
            return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
        } catch (Throwable ignored) {
            return "1970-01-01";
        }
    }

    private static String firstMatch(String text, String... patterns) {
        if (text == null) {
            return "";
        }
        for (String patternText : patterns) {
            try {
                java.util.regex.Matcher matcher = Pattern.compile(patternText).matcher(text);
                if (matcher.find()) {
                    String value = matcher.group(1);
                    return value == null ? "" : value;
                }
            } catch (Throwable ignored) {
            }
        }
        return "";
    }

    private static String sanitizeFileName(String name) {
        String cleaned = name.replaceAll("[\\\\/:*?\"<>|\\r\\n\\t]", "_")
                .replaceAll("\\s+", "_")
                .replaceAll("_+", "_");
        if (cleaned.length() > HOTEL_FILE_NAME_LIMIT) {
            cleaned = cleaned.substring(0, HOTEL_FILE_NAME_LIMIT);
        }
        while (cleaned.endsWith(".") || cleaned.endsWith("_")) {
            cleaned = cleaned.substring(0, cleaned.length() - 1);
        }
        return cleaned.length() == 0 ? "hotel_detail" : cleaned;
    }

    private static String safeToString(Object value) {
        if (value == null) {
            return "null";
        }
        try {
            if (value instanceof Map) {
                return mapToString((Map<?, ?>) value);
            }
            return String.valueOf(value);
        } catch (Throwable error) {
            return "<" + value.getClass().getName() + ">";
        }
    }

    private static String mapToString(Map<?, ?> map) {
        StringBuilder builder = new StringBuilder();
        builder.append("{");
        boolean first = true;
        int count = 0;
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (!first) {
                builder.append(", ");
            }
            first = false;
            builder.append(String.valueOf(entry.getKey())).append("=")
                    .append(String.valueOf(entry.getValue()));
            count++;
            if (count >= 200) {
                builder.append(", ...[map-truncated]");
                break;
            }
        }
        builder.append("}");
        return builder.toString();
    }

    private static String sanitize(String text) {
        String sanitized = text;
        for (Pattern pattern : SENSITIVE_QUERY_PATTERNS) {
            sanitized = pattern.matcher(sanitized).replaceAll("$1=<redacted>");
        }
        for (Pattern pattern : SENSITIVE_JSON_PATTERNS) {
            sanitized = pattern.matcher(sanitized).replaceAll("$1<redacted>\"");
        }
        for (Pattern pattern : SENSITIVE_STANDALONE_PATTERNS) {
            sanitized = pattern.matcher(sanitized).replaceAll("<redacted>");
        }
        return sanitized;
    }

    private static String truncateForPreference(String text) {
        if (text.length() > PREF_VALUE_LIMIT) {
            return text.substring(0, PREF_VALUE_LIMIT) + "...[pref-truncated]";
        }
        return text;
    }

    private static boolean shouldLogHttpUrl(String url) {
        if (url == null || "null".equals(url) || isStaticResourceUrl(url)) {
            return false;
        }
        String lower = url.toLowerCase(Locale.US);
        if (lower.contains("/restapi/soa2/")) {
            return true;
        }
        return lower.contains("ws-p.tripcdn.cn/html5/") && lower.contains("rn_");
    }

    private static boolean shouldLogHttpBodyUrl(String url) {
        if (url == null || "null".equals(url) || isStaticResourceUrl(url)) {
            return false;
        }
        String lower = url.toLowerCase(Locale.US);
        return lower.contains("/restapi/soa2/32440/getdetailadditionalinfo")
                || lower.contains("rn_xtaro_hotel_detail")
                || lower.contains("hotel_inland_detail")
                || (lower.contains("/restapi/soa2/") && lower.contains("hotel") && lower.contains("detail"));
    }

    private static boolean shouldLogWebUrl(String url) {
        if (url == null || "null".equals(url) || isStaticResourceUrl(url)) {
            return false;
        }
        String lower = url.toLowerCase(Locale.US);
        return lower.startsWith("http://")
                || lower.startsWith("https://")
                || lower.startsWith("ctrip://")
                || lower.startsWith("ctripapp://");
    }

    private static boolean shouldLogPreferenceKey(String key, String value) {
        String text = ((key == null ? "" : key) + " " + (value == null ? "" : value))
                .toLowerCase(Locale.US);
        if (text.length() == 0 || text.startsWith("plc")) {
            return false;
        }
        return text.contains("url")
                || text.contains("host")
                || text.contains("server")
                || text.contains("env")
                || text.contains("page")
                || text.contains("action")
                || text.contains("client")
                || text.contains("sid")
                || text.contains("token")
                || text.contains("cookie")
                || text.contains("auth")
                || text.contains("ip_list")
                || text.contains("dispatch")
                || text.contains("http")
                || text.contains("tcp");
    }

    private static boolean isStaticResourceUrl(String url) {
        String lower = url.toLowerCase(Locale.US);
        if (lower.contains("ma-adx.ctrip.com/_ma.gif")) {
            return true;
        }
        String path = lower;
        int queryIndex = path.indexOf('?');
        if (queryIndex >= 0) {
            path = path.substring(0, queryIndex);
        }
        return path.endsWith(".png")
                || path.endsWith(".jpg")
                || path.endsWith(".jpeg")
                || path.endsWith(".gif")
                || path.endsWith(".webp")
                || path.endsWith(".avif")
                || path.endsWith(".svg")
                || path.endsWith(".css")
                || path.endsWith(".js")
                || path.endsWith(".woff")
                || path.endsWith(".woff2")
                || path.endsWith(".ttf")
                || path.endsWith(".ctz");
    }

    private static String normalizeUrlForLog(String url) {
        int queryIndex = url.indexOf('?');
        if (queryIndex < 0) {
            return url;
        }
        String query = url.substring(queryIndex + 1);
        if (query.length() > 800) {
            return url.substring(0, queryIndex + 1) + query.substring(0, 800) + "...[query-truncated]";
        }
        return url;
    }

    private static boolean markRecent(String key) {
        long now = System.currentTimeMillis();
        synchronized (RECENT_LOGS) {
            Long last = RECENT_LOGS.get(key);
            if (last != null && now - last < DUPLICATE_LOG_WINDOW_MS) {
                return false;
            }
            RECENT_LOGS.put(key, now);
            return true;
        }
    }

    private static String truncate(String text) {
        if (text.length() > LOG_LIMIT) {
            return text.substring(0, LOG_LIMIT) + "...[truncated]";
        }
        return text;
    }

    private static void log(String message) {
        XposedBridge.log(TAG + ": " + message);
    }

    private static final class MonitoredInputStream extends FilterInputStream {
        private final String endpoint;
        private int dumped;
        private int sequence;

        MonitoredInputStream(InputStream input, String endpoint) {
            super(input);
            this.endpoint = endpoint;
        }

        @Override
        public int read() throws IOException {
            int value = super.read();
            if (value >= 0) {
                byte[] one = new byte[]{(byte) value};
                logInbound(one, 0, 1);
            }
            return value;
        }

        @Override
        public int read(byte[] buffer) throws IOException {
            return read(buffer, 0, buffer.length);
        }

        @Override
        public int read(byte[] buffer, int offset, int length) throws IOException {
            int count = in.read(buffer, offset, length);
            if (count > 0) {
                logInbound(buffer, offset, count);
            }
            return count;
        }

        private void logInbound(byte[] buffer, int offset, int length) {
            if (dumped >= TCP_STREAM_DUMP_LIMIT) {
                return;
            }
            int count = Math.min(length, TCP_STREAM_DUMP_LIMIT - dumped);
            dumped += count;
            logTcpBytes("IN", endpoint, buffer, offset, count, ++sequence);
        }
    }

    private static final class MonitoredOutputStream extends FilterOutputStream {
        private final String endpoint;
        private int dumped;
        private int sequence;

        MonitoredOutputStream(OutputStream output, String endpoint) {
            super(output);
            this.endpoint = endpoint;
        }

        @Override
        public void write(int value) throws IOException {
            out.write(value);
            byte[] one = new byte[]{(byte) value};
            logOutbound(one, 0, 1);
        }

        @Override
        public void write(byte[] buffer) throws IOException {
            if (buffer != null) {
                write(buffer, 0, buffer.length);
            }
        }

        @Override
        public void write(byte[] buffer, int offset, int length) throws IOException {
            out.write(buffer, offset, length);
            logOutbound(buffer, offset, length);
        }

        private void logOutbound(byte[] buffer, int offset, int length) {
            if (buffer == null || length <= 0 || dumped >= TCP_STREAM_DUMP_LIMIT) {
                return;
            }
            int count = Math.min(length, TCP_STREAM_DUMP_LIMIT - dumped);
            dumped += count;
            logTcpBytes("OUT", endpoint, buffer, offset, count, ++sequence);
        }
    }
}
