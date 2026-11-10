# Android app (WebView shell)

Same UI as the web app. The Python backend on your Mac still does all STT.

## Requirements

- Android Studio Ladybug+ (or SDK 35 + JDK 17)
- Phone on the same Tailscale account as the Mac
- Mac running: `python server.py --https --host 0.0.0.0`

## Open & run

1. Open the `android/` folder in Android Studio  
2. Let Gradle sync  
3. Plug in your Pixel (USB debugging on) or use an emulator  
4. Run **app**

Default server URL: `https://100.79.49.115:8443`  
Change it in the app with the gear icon if your Tailscale IP changes.

## First launch

1. Allow **microphone** when Android asks  
2. The self-signed HTTPS cert for your configured host is accepted automatically  
3. Use Record / Upload exactly like in the browser  

## Build a release APK

```bash
cd android
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

## Maintain

Edit `static/` on the Mac as usual — the phone app just reloads that page.  
No need to rebuild the Android app for UI/mixer/transcript changes.
