# Android WebView shell for auto ASR

## Goal

Ship an Android app that loads the existing web UI from the Python backend
(Tailscale / LAN HTTPS). No duplicate STT logic.

## Approach

- Kotlin + WebView
- Configurable server base URL (default Tailscale HTTPS)
- Mic + media permissions for `getUserMedia`
- Trust the project's self-signed cert for that host only
- Backend unchanged

## Non-goals

- Native UI rewrite
- Bundling Whisper on-device
