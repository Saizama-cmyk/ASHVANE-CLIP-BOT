import React, {useEffect, useMemo, useRef, useState} from "react";
import {Text, View} from "react-native";
import {acceptSceneMessage, sceneMessage} from "./coreSceneData";
import {C, t} from "./theme";

export default function CoreScene({host, snapshot, selected, onSelect, active = true}) {
  const frame = useRef(null), [status, setStatus] = useState("loading");
  useEffect(() => { setStatus("loading"); const timer = setTimeout(()=>setStatus(value=>value==="loading"?"unavailable":value),8000); return ()=>clearTimeout(timer); }, [host]);
  const origin = useMemo(() => new URL(host).origin, [host]);
  const source = `${host}/static/supervisor-phone.html?parent_origin=${encodeURIComponent(window.location.origin)}`;
  const send = () => frame.current?.contentWindow?.postMessage(sceneMessage(snapshot, selected, active), origin);
  useEffect(() => { send(); }, [host, snapshot, selected, active]);
  useEffect(() => {
    const receive = event => {
      if (event.source !== frame.current?.contentWindow || event.origin !== origin) return;
      const result = acceptSceneMessage(event.data, snapshot);
      if (result?.id) onSelect(result.id);
      if (result?.status) { setStatus(result.status); if (result.status === "ready") send(); }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [snapshot, selected, active, origin, onSelect]);
  return <View style={{height: 310, backgroundColor: C.bg, overflow: "hidden", borderRadius: 14}}>
    <iframe ref={frame} src={source} title="Interactive agent constellation" onLoad={send} onError={() => setStatus("unavailable")}
      sandbox="allow-scripts allow-same-origin" referrerPolicy="no-referrer" style={{width: "100%",height: "100%",border:0,background:C.bg}} />
    {status !== "ready" && <View pointerEvents="none" style={{position: "absolute",bottom:14,left:20,right:20}}><Text style={t.faint}>{status === "loading" ? "Connecting to the local Core scene…" : "3D view unavailable. Select an agent from the roster below."}</Text></View>}
  </View>;
}
