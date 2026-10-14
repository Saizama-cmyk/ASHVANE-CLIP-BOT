import React, { useCallback, useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, AppState, Easing, StyleSheet, View } from "react-native";
import { C } from "./theme";

// A single spatial transition when crossing between businesses. It animates the live shell,
// including its header and tabs. No screenshots, persistent animation loop or hidden content.
const businessFor = tab => ["core", "tools", "chat", "code"].includes(tab) ? null : tab === "stories" || tab.startsWith("story-") ? "stories" : tab === "music" || tab.startsWith("music-") ? "music" : tab === "social" || tab.startsWith("social-") ? "social" : "clips";

export function usePortal(initial = "desk") {
  const [tab, setTab] = useState(initial);
  const [crossing, setCrossing] = useState(false);
  const [reduced, setReduced] = useState(true);
  const amount = useRef(new Animated.Value(0)).current;
  const current = useRef(initial), destination = useRef(initial), animation = useRef(null);
  const live = useRef(true), running = useRef(false);
  useEffect(() => {
    live.current = true;
    AccessibilityInfo.isReduceMotionEnabled().then(value => { if (live.current) setReduced(value); }).catch(() => {});
    const motion = AccessibilityInfo.addEventListener("reduceMotionChanged", setReduced);
    const app = AppState.addEventListener("change", next => {
      if (next !== "active") {
        animation.current?.stop(); running.current = false; amount.setValue(0);
        current.current = destination.current; setTab(destination.current); setCrossing(false);
      }
    });
    return () => { live.current = false; animation.current?.stop(); amount.setValue(0); motion.remove(); app.remove(); };
  }, [amount]);
  const navigate = useCallback(next => {
    destination.current = next;
    if (running.current || next === current.current) return;
    if (reduced || !businessFor(next) || !businessFor(current.current) || businessFor(next) === businessFor(current.current)) { current.current = next; setTab(next); return; }
    running.current = true; setCrossing(true);
    const out = Animated.timing(amount, { toValue: 1, duration: reduced ? 90 : 500, easing: Easing.out(Easing.cubic), useNativeDriver: true });
    animation.current = out;
    out.start(({ finished }) => {
      if (!finished || !live.current) return;
      current.current = destination.current; setTab(destination.current);
      const back = Animated.timing(amount, { toValue: 0, duration: reduced ? 90 : 650, easing: Easing.out(Easing.cubic), useNativeDriver: true });
      animation.current = back;
      back.start(({ finished: returned }) => {
        if (!returned || !live.current) return;
        running.current = false; setCrossing(false); amount.setValue(0);
        // Rapid navigation always lands on the last requested destination.
        if (current.current !== destination.current) { current.current = destination.current; setTab(destination.current); }
      });
    });
  }, [amount, reduced]);
  const shellStyle = reduced
    ? { flex: 1, opacity: amount.interpolate({ inputRange: [0, 1], outputRange: [1, 0] }) }
    : { flex: 1, opacity: amount.interpolate({ inputRange: [0, 1], outputRange: [1, 0.06] }), transform: [
      { perspective: 900 }, { scale: amount.interpolate({ inputRange: [0, 0.55, 1], outputRange: [1, 0.42, 0.012] }) },
      { rotate: amount.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "-84deg"] }) },
      { rotateY: amount.interpolate({ inputRange: [0, 1], outputRange: ["0deg", "38deg"] }) },
    ] };
  return { tab, navigate, shellStyle, crossing, amount, reduced };
}

export function PortalOverlay({ portal }) {
  if (!portal.crossing || portal.reduced) return null;
  return <View pointerEvents="none" accessible={false} importantForAccessibility="no-hide-descendants" style={styles.overlay}>
    <Animated.View style={{ opacity: portal.amount, transform: [{ scale: portal.amount.interpolate({ inputRange: [0, 1], outputRange: [0.55, 1.3] }) }] }}>
      <GravityMark size={250} />
    </Animated.View>
  </View>;
}
/** Original photon-ring mark; static outside the bounded portal/launch reveal. */
export function GravityMark({size = 160}) {
  return <View accessible={false} style={{width: size, height: size, alignItems: "center", justifyContent: "center"}}>
    <View style={{position: "absolute", width: size * .78, height: size * .78, borderRadius: size, borderWidth: 1, borderColor: C.line2, backgroundColor: C.bg}} />
    {[1, .94, .86].map((scale, index) => <View key={scale} style={{position: "absolute", width: size * scale, height: size * .32 * scale, borderRadius: size, borderWidth: index === 1 ? 3 : 1, borderColor: index === 1 ? C.ember : "rgba(241,188,122,.27)", transform: [{rotate: "-23deg"}]}} />)}
    <View style={{width: size * .48, height: size * .48, borderRadius: size, backgroundColor: C.bg, borderWidth: 2, borderColor: C.ember}} />
    <View style={{position: "absolute", width: size * .7, height: size * .13, borderBottomWidth: 2, borderColor: C.ink, borderRadius: size, transform: [{rotate: "-23deg"}]}} />
  </View>;
}
const styles = StyleSheet.create({
  overlay: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
});
