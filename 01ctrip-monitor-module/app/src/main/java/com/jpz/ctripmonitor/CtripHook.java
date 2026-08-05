package com.jpz.ctripmonitor;

import android.app.Application;
import android.content.Context;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

import de.robv.android.xposed.IXposedHookLoadPackage;
import de.robv.android.xposed.XC_MethodHook;
import de.robv.android.xposed.XposedBridge;
import de.robv.android.xposed.XposedHelpers;
import de.robv.android.xposed.callbacks.XC_LoadPackage;

public final class CtripHook implements IXposedHookLoadPackage {
    private static final String TAG = "CtripMonitor";

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
                        ClassLoader loader = context.getClassLoader();
                        log("classLoader ready process=" + lpparam.processName);
                        installGsonHooks(loader);
                        installOkHttpHooks(loader);
                    }
                });
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
                    log("HTTP " + method + " " + url);
                }
            });

            log("OkHttp hooks installed");
        } catch (Throwable error) {
            log("OkHttp unavailable: " + error.getClass().getSimpleName());
        }
    }

    private static void logValue(String source, Object value) {
        String text = String.valueOf(value);
        int limit = 4000;
        if (text.length() > limit) {
            text = text.substring(0, limit) + "...[truncated]";
        }
        log(source + ": " + text);
    }

    private static void log(String message) {
        XposedBridge.log(TAG + ": " + message);
    }
}
