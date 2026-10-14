import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {Text, View} from "react-native";
import {WebView} from "react-native-webview";
import {acceptSceneMessage, safeSceneJSON, sceneMessage} from "./coreSceneData";
import {C, t} from "./theme";

export default function CoreScene({host, snapshot, selected, onSelect, active = true}) {
  const frame = useRef(null), [status, setStatus] = useState("loading");
  useEffect(() => { setStatus("loading"); const timer = setTimeout(()=>setStatus(value=>value==="loading"?"unavailable":value),8000); return ()=>clearTimeout(timer); }, [host]);
  const source = useMemo(() => ({uri: `${host}/static/supervisor-phone.html`}), [host]);
  const message = useMemo(() => safeSceneJSON(sceneMessage(snapshot, selected, active)), [snapshot, selected, active]);
  const send = useCallback(() => frame.current?.injectJavaScript(`window.dispatchEvent(new MessageEvent('message',{data:${message}}));true;`), [message]);
  useEffect(() => { send(); }, [send]);
  const receive = event => {
    const result = acceptSceneMessage(event.nativeEvent.data, snapshot);
    if (result?.id) onSelect(result.id);
    if (result?.status) { setStatus(result.status); if (result.status === "ready") send(); }
  };
  return <View style={{height: 310, backgroundColor: C.bg, overflow: "hidden", borderRadius: 14}}>
    <WebView ref={frame} source={source} style={{flex: 1, backgroundColor: C.bg}} javaScriptEnabled
      originWhitelist={[host]} onShouldStartLoadWithRequest={request => request.url === source.uri || request.url === "about:blank"}
      onLoadEnd={send} onMessage={receive} onError={() => setStatus("unavailable")} onHttpError={() => setStatus("unavailable")}
      sharedCookiesEnabled={false} thirdPartyCookiesEnabled={false} setSupportMultipleWindows={false} allowsInlineMediaPlayback={false}
      accessibilityLabel="Interactive agent constellation" />
    {status !== "ready" && <View pointerEvents="none" style={{position: "absolute", bottom: 14, left: 20, right: 20}}><Text style={t.faint}>{status === "loading" ? "Connecting to the local Core scene…" : "3D view unavailable. Select an agent from the roster below."}</Text></View>}
  </View>;
}
