/**
 * An original observatory instrument deck: cool hull surfaces, pale instrument lettering,
 * restrained amber controls. Depth comes from tonal steps and rails rather than decoration.
 */
import React, {useState} from "react";
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";

export const C = {
  bg: "#05070D", s1: "#0E1523", s2: "#172233", s3: "#202E42", s4: "#273449",
  line: "#273449", line2: "#485A74",
  ink: "#F0F4FA", ink2: "#B8C5D7", ink3: "#9FADC2",
  ember: "#F1BC7A", emberSoft: "rgba(241,188,122,0.10)", emberLine: "rgba(241,188,122,0.46)",
  good: "#79DCCA", goodSoft: "rgba(121,220,202,0.10)",
  bad: "#FF8E88", badSoft: "rgba(255,142,136,0.10)",
  warn: "#F1BC7A",
};
export const HEAD = Platform.OS === "web" ? "SpaceGrotesk, system-ui, sans-serif" : "SpaceGrotesk";
export const BODY = Platform.OS === "web" ? "IBMPlexSans, system-ui, sans-serif" : "IBMPlexSans";
export const MONO = Platform.select({ ios: "Menlo", android: "monospace", default: "ui-monospace, Menlo, monospace" });
export const GUTTER = 20;
export const BUSINESS_COLORS = {clips: C.ember, stories: "#C8AFE7", music: "#79DCCA", social: "#9CBCE8"};

export const t = StyleSheet.create({
  title: { color: C.ink, fontFamily: HEAD, fontSize: 28, fontWeight: "600", letterSpacing: -0.7, lineHeight: 34 },
  h2: { color: C.ink, fontFamily: HEAD, fontSize: 19, fontWeight: "600", letterSpacing: -0.3, lineHeight: 25 },
  body: { color: C.ink, fontFamily: BODY, fontSize: 15, lineHeight: 22 },
  muted: { color: C.ink2, fontFamily: BODY, fontSize: 14, lineHeight: 21 },
  faint: { color: C.ink3, fontFamily: BODY, fontSize: 12, lineHeight: 18 },
  label: { color: C.ink3, fontFamily: BODY, fontSize: 13, fontWeight: "600", letterSpacing: 0.1 },
  mono: { color: C.ink, fontFamily: MONO, fontSize: 13 },
  num: { color: C.ink, fontFamily: HEAD, fontSize: 30, fontWeight: "500", fontVariant: ["tabular-nums"], letterSpacing: -0.7 },
  error: { color: C.bad, fontSize: 13.5, lineHeight: 19 },
});

/** A surface. `tone` steps it lighter; `pad={false}` for full-bleed lists. */
export function Card({ children, style, tone = 1, pad = true }) {
  return <View style={[st.card, { backgroundColor: tone === 2 ? C.s2 : C.s1 }, pad && st.cardPad, style]}>{children}</View>;
}

export function Section({ title, right, children, style }) {
  return (
    <View style={[{ marginBottom: 28 }, style]}>
      {(title || right) && (
        <View style={st.sectionHead}>
          <Text style={[t.label, { flex: 1 }]}>{title}</Text>
          {right}
        </View>)}
      {children}
    </View>);
}

export function Icon({ name, size = 20, color = C.ink2, style }) {
  return <Ionicons name={name} size={size} color={color} style={style} />;
}

/** kind: primary (ember), plain (tonal), ghost (text only), danger. */
export function Button({ label, icon, onPress, kind = "plain", busy, disabled, small, style, grow, accessibilityState }) {
  const [focused,setFocused] = useState(false);
  const k = BTN[kind] || BTN.plain;
  const ink = disabled || busy ? C.ink2 : k.ink;
  return (
    <Pressable onPress={onPress} onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)} disabled={disabled || busy} accessibilityRole="button" accessibilityLabel={label}
      accessibilityState={{ ...accessibilityState, disabled: !!(disabled || busy), busy: !!busy }} style={({ pressed }) => [st.btn, small && st.btnSmall, { backgroundColor: k.bg, borderColor: k.border },
        grow && { flex: 1 }, (disabled || busy) && { backgroundColor: C.s2, borderColor: C.line2 }, pressed && { opacity: 0.78 }, focused && {borderColor:C.ember}, focused && Platform.OS==="web" && {outlineStyle:"solid",outlineWidth:2,outlineColor:C.ember,outlineOffset:3}, style]}>
      {busy ? <ActivityIndicator color={ink} size="small" /> : (
        <>
          {!!icon && <Icon name={icon} size={small ? 16 : 18} color={ink} />}
          {!!label && <Text style={[st.btnText, small && { fontSize: 13.5 }, { color: ink }]}>{label}</Text>}
        </>)}
    </Pressable>);
}
const BTN = {
  primary: { bg: C.ember, border: C.ember, ink: "#1A0D06" },
  plain: { bg: C.s3, border: C.line, ink: C.ink },
  ghost: { bg: "transparent", border: "transparent", ink: C.ink2 },
  danger: { bg: C.badSoft, border: "rgba(255,142,136,0.35)", ink: C.bad },
};

export function IconButton({ icon, onPress, label, color = C.ink2, size = 20, style, disabled }) {
  const [focused,setFocused] = useState(false);
  return (
    <Pressable onPress={onPress} onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)} disabled={disabled} hitSlop={10} accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ disabled: !!disabled }}
      style={({ pressed }) => [st.iconBtn, (pressed || focused) && { backgroundColor: C.s3 }, focused && Platform.OS==="web" && {outlineStyle:"solid",outlineWidth:2,outlineColor:C.ember,outlineOffset:2}, disabled && { opacity: 0.35 }, style]}>
      <Icon name={icon} size={size} color={color} />
    </Pressable>);
}

/** A row of choices where exactly one is on. */
export function Segmented({ options, value, onChange, style }) {
  return (
    <View style={[st.seg, style]}>
      {options.map(([key, label]) => {
        const on = key === value;
        return (
          <Pressable key={key} onPress={() => onChange(key)} accessibilityRole="tab" accessibilityState={{ selected: on }}
            style={({ pressed }) => [st.segItem, on && st.segOn, pressed && {backgroundColor: C.s3}]}>
            <Text style={[st.segText, on && { color: C.ink }]} numberOfLines={1}>{label}</Text>
          </Pressable>);
      })}
    </View>);
}

export function Pill({ label, tone = "plain", icon }) {
  const p = PILL[tone] || PILL.plain;
  return (
    <View style={[st.pill, { backgroundColor: p.bg, borderColor: p.border }]}>
      {tone !== "plain" && !icon && <View style={[st.pillDot, { backgroundColor: p.ink }]} />}
      {!!icon && <Icon name={icon} size={12} color={p.ink} />}
      <Text style={[st.pillText, { color: p.ink }]} numberOfLines={1}>{label}</Text>
    </View>);
}
const PILL = {
  plain: { bg: C.s3, border: C.line, ink: C.ink2 },
  live: { bg: C.emberSoft, border: C.emberLine, ink: C.ember },
  good: { bg: C.goodSoft, border: "rgba(121,220,202,0.35)", ink: C.good },
  bad: { bg: C.badSoft, border: "rgba(255,142,136,0.35)", ink: C.bad },
};

export function Field({ label, style, inputStyle, mono, ...props }) {
  const [focused,setFocused] = useState(false);
  return (
    <View style={style}>
      {!!label && <Text style={[t.label, { marginBottom: 6 }]}>{label}</Text>}
      <TextInput placeholderTextColor={C.ink3} selectionColor={C.ember} cursorColor={C.ember}
        style={[st.input, mono && { fontFamily: MONO, fontSize: 14 }, props.multiline && { minHeight: 88, paddingTop: 12, textAlignVertical: "top" }, focused && {borderColor:C.ember}, inputStyle]}
        {...props} onFocus={event=>{setFocused(true);props.onFocus?.(event);}} onBlur={event=>{setFocused(false);props.onBlur?.(event);}} accessibilityLabel={props.accessibilityLabel || label} />
    </View>);
}

export function Divider({ style }) { return <View style={[st.divider, style]} />; }

export function Empty({ icon = "sparkles-outline", title, body, children }) {
  return (
    <View style={st.empty}>
      <View style={st.emptyIcon}><Icon name={icon} size={22} color={C.ink2} /></View>
      {!!title && <Text style={[t.h2, { textAlign: "center" }]}>{title}</Text>}
      {!!body && <Text style={[t.muted, { textAlign: "center", marginTop: 6 }]}>{body}</Text>}
      {children}
    </View>);
}

/** A list row: icon, title, subtitle, and whatever sits on the right. */
export function ListRow({ icon, title, sub, right, onPress, onLongPress, first, danger }) {
  const body = (
    <View style={[st.row, !first && st.rowLine]}>
      {!!icon && <View style={st.rowIcon}><Icon name={icon} size={18} color={danger ? C.bad : C.ink2} /></View>}
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={[t.body, { fontWeight: "600" }, danger && { color: C.bad }]} numberOfLines={1}>{title}</Text>
        {!!sub && <Text style={[t.faint, { marginTop: 2 }]} numberOfLines={2}>{sub}</Text>}
      </View>
      {right}
    </View>);
  if (!onPress && !onLongPress) return body;
  return <Pressable onPress={onPress} onLongPress={onLongPress} accessibilityRole="button" accessibilityLabel={title} style={({ pressed }) => pressed && { backgroundColor: C.s2 }}>{body}</Pressable>;
}

/** The shared style keys the chat pieces (Chat.js) were written against. */
export const chatStyles = StyleSheet.create({
  label: t.label,
  help: { ...t.faint, marginTop: 4 },
  monName: { color: C.ink, fontSize: 15, fontWeight: "600" },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  input: { marginTop: 6, minHeight: 46, borderRadius: 12, paddingHorizontal: 14, backgroundColor: C.s2,
    color: C.ink, fontSize: 15.5, borderWidth: 1, borderColor: C.line },
  error: { ...t.error, marginTop: 10 },
  bubbleText: { color: C.ink, fontSize: 15.5, lineHeight: 22 },
  bubbleMineText: { color: C.ink, fontSize: 15.5, lineHeight: 22 },
});

const st = StyleSheet.create({
  card: { borderRadius: 14, overflow: "hidden" },
  cardPad: { padding: 20 },
  sectionHead: { flexDirection: "row", alignItems: "center", marginBottom: 10, paddingHorizontal: 0, minHeight: 22 },
  btn: { minHeight: 48, borderRadius: 8, paddingHorizontal: 18, flexDirection: "row", gap: 8,
    alignItems: "center", justifyContent: "center", borderWidth: 1 },
  btnSmall: { minHeight: 44, paddingHorizontal: 14, borderRadius: 8 },
  btnText: { fontFamily: BODY, fontSize: 15, fontWeight: "600" },
  iconBtn: { width: 44, height: 44, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  seg: { flexDirection: "row", backgroundColor: C.s1, borderRadius: 8, padding: 3 },
  segItem: { flex: 1, minHeight: 44, borderRadius: 6, alignItems: "center", justifyContent: "center", paddingHorizontal: 6 },
  segOn: { backgroundColor: C.s3 },
  segText: { color: C.ink3, fontFamily: BODY, fontSize: 13.5, fontWeight: "600" },
  pill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, height: 26, borderRadius: 13, borderWidth: 1 },
  pillDot: { width: 6, height: 6, borderRadius: 3 },
  pillText: { fontFamily: BODY, fontSize: 12, fontWeight: "600" },
  input: { minHeight: 48, borderRadius: 8, paddingHorizontal: 14, backgroundColor: C.s2, color: C.ink,
    fontFamily: BODY, fontSize: 16, borderWidth: 1, borderColor: C.line },
  divider: { height: 1, backgroundColor: C.line },
  empty: { alignItems: "center", paddingVertical: 28, paddingHorizontal: 20 },
  emptyIcon: { width: 48, height: 48, borderRadius: 14, backgroundColor: C.s2, alignItems: "center",
    justifyContent: "center", marginBottom: 12, borderWidth: 1, borderColor: C.line },
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 13, minHeight: 56 },
  rowLine: { borderTopWidth: 1, borderTopColor: C.line },
  rowIcon: { width: 34, height: 34, borderRadius: 10, backgroundColor: C.s2, alignItems: "center", justifyContent: "center" },
});
