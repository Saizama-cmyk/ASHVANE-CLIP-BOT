/** One finite launch reveal. It represents navigation, never production progress. */
import React, {useEffect, useRef} from "react";
import {AccessibilityInfo, Animated, Easing, StyleSheet, Text, View} from "react-native";
import {GravityMark} from "./Portal";
import {C, HEAD, t} from "./theme";

export default function Splash({onDone}) {
  const reveal = useRef(new Animated.Value(0)).current;
  const finish = useRef(onDone); finish.current = onDone;
  useEffect(() => {
    let alive = true, animation;
    AccessibilityInfo.isReduceMotionEnabled().then(reduced => {
      if (!alive) return;
      if (reduced) { finish.current(); return; }
      animation = Animated.timing(reveal, {toValue: 1, duration: 1350, easing: Easing.bezier(.2,.75,.2,1), useNativeDriver: true});
      animation.start(({finished}) => { if (finished && alive) finish.current(); });
    }).catch(() => { if (alive) finish.current(); });
    return () => { alive = false; animation?.stop(); };
  }, [reveal]);
  return <Animated.View pointerEvents="none" accessible={false} importantForAccessibility="no-hide-descendants" style={[StyleSheet.absoluteFillObject, {backgroundColor: C.bg, zIndex: 100, justifyContent: "center", alignItems: "center", opacity: reveal.interpolate({inputRange: [0,.64,1],outputRange: [1,1,0]})}]}>
    <Animated.View style={{transform: [{scale: reveal.interpolate({inputRange:[0,.6,1],outputRange:[.8,1,2.2]})}, {rotate: reveal.interpolate({inputRange:[0,1],outputRange:["-10deg","8deg"]})}]}}><GravityMark size={220} /></Animated.View>
    <View style={{alignItems:"center", marginTop: 28}}><Text style={{fontFamily:HEAD,fontSize:34,letterSpacing:-1,color:C.ink}}>Ashvane</Text><Text style={[t.faint,{marginTop:10}]}>The living observatory</Text></View>
  </Animated.View>;
}
