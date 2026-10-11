import React, { useEffect, useState } from "react";
import { ActivityIndicator, Image, Platform, Text, View } from "react-native";
import * as FileSystem from "expo-file-system";
import { WebView } from "react-native-webview";
import { C, t } from "./theme";

// Media stays behind the same authenticated server as the workspace. Tokens never enter URLs.
export default function BusinessMedia({ host, token, path, kind = "audio", onUnauthorized, label = "Private preview" }) {
  const [uri, setUri] = useState(""), [error, setError] = useState("");
  useEffect(() => {
    let alive = true, directory = "", objectUrl = "", downloader;
    const controller = new AbortController(); setUri(""); setError("");
    (async () => {
      if (!/^\/api\/(music|social)\//.test(path || "") || path.includes("..") || /[?#]/.test(path)) throw new Error("This preview is not registered with the PC.");
      if (Platform.OS === "web") {
        const response = await fetch(host + path, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
        if (response.status === 401) onUnauthorized?.(true);
        if (!response.ok) throw new Error("The PC could not provide this preview.");
        const blob = await response.blob();
        if (!alive) return;
        objectUrl = URL.createObjectURL(blob); setUri(objectUrl);
      } else {
        directory = `${FileSystem.cacheDirectory}workspace-${Date.now()}-${Math.random().toString(36).slice(2)}/`;
        await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
        const extension = kind === "video" ? "mp4" : kind === "image" ? "png" : "wav";
        downloader = FileSystem.createDownloadResumable(host + path, `${directory}preview.${extension}`, { headers: { Authorization: `Bearer ${token}` } });
        const result = await downloader.downloadAsync();
        if (result?.status === 401) onUnauthorized?.(true);
        if (!result || result.status !== 200) throw new Error("The PC could not provide this preview.");
        if (kind === "image") { if (alive) setUri(result.uri); return; }
        await FileSystem.writeAsStringAsync(`${directory}index.html`, `<!doctype html><html><body style="margin:0;background:#070A10"><${kind} controls style="width:100%;max-height:420px" src="preview.${extension}"></${kind}></body></html>`);
        if (alive) setUri(`${directory}index.html`);
      }
    })().catch(e => { if (alive && e.name !== "AbortError") setError(e.message || "Preview could not load."); });
    return () => {
      alive = false; controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl);
      (async () => { if (downloader) await downloader.pauseAsync().catch(() => {}); if (directory) await FileSystem.deleteAsync(directory, { idempotent: true }).catch(() => {}); })();
    };
  }, [host, token, path, kind, onUnauthorized]);
  return <View style={{ gap: 10 }}><Text style={t.label}>{label}</Text>
    {!!error && <Text accessibilityRole="alert" style={t.error}>{error}</Text>}
    {!uri && !error && <ActivityIndicator accessibilityLabel="Loading authenticated preview" color={C.ember} />}
    {!!uri && (kind === "image" ? <Image source={{ uri }} resizeMode="contain" accessibilityLabel={label} style={{ width: "100%", height: 220 }} /> : Platform.OS === "web" ? React.createElement(kind, { src: uri, controls: true, "aria-label": label, style: { width: "100%", maxHeight: 420 } }) : <WebView source={{ uri }} style={{ height: kind === "audio" ? 80 : 420, backgroundColor: C.bg }} originWhitelist={["file://*"]} allowingReadAccessToURL={uri.replace(/index\.html$/, "")} allowFileAccess allowFileAccessFromFileURLs allowsInlineMediaPlayback onShouldStartLoadWithRequest={r => r.url.startsWith("file://") || r.url === "about:blank"} onError={() => setError("This phone could not play the preview.")} />)}
  </View>;
}
