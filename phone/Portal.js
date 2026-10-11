import React, { useCallback, useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Animated, AppState, Easing, StyleSheet, View } from "react-native";
import { C } from "./theme";

// A single spatial transition when crossing the Stories boundary. It animates the live shell,
// including its header and tabs. No screenshots, persistent animation loop or hidden content.
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
    if ((next === "stories") === (current.current === "stories")) { current.current = next; setTab(next); return; }
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
      <View style={styles.halo} /><View style={styles.orbit} /><View style={styles.horizon} />
    </Animated.View>
  </View>;
}
const styles = StyleSheet.create({
  overlay: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  halo: { width: 220, height: 220, borderRadius: 110, borderWidth: 1, borderColor: "#40566B", backgroundColor: "#070A10" },
  orbit: { position: "absolute", width: 284, height: 64, top: 78, left: -32, borderRadius: 142, borderWidth: 3, borderColor: C.ember, transform: [{ rotate: "-24deg" }] },
  horizon: { position: "absolute", width: 156, height: 156, top: 32, left: 32, borderRadius: 78, backgroundColor: "#000000", borderWidth: 2, borderColor: "#DFE8ED" },
});
