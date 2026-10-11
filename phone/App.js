/**
 * Ashvane on the phone: four independently controlled businesses and shared tools.
 *
 *   Desk       the clip desk on your PC, over your own Wi-Fi or Tailscale
 *   Stories    original narrated horror production and its own publishing controls
 *   Research   original scripts and posts grounded in linked sources
 *   Tools      the private Assistant and Code workspace, available on demand
 *
 * The phone signs in to the PC once (your profile password) and keeps the session token in the
 * keychain; the PC keeps that sign-in for weeks. Face ID / fingerprint guards the app itself.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Animated, AppState, Image, Linking, Platform, Pressable, RefreshControl, ScrollView, StatusBar, Text, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import Constants from "expo-constants";
import { LockScreen, useLock } from "./Lock";
import { call, KEY_HOST, KEY_TOKEN } from "./api";
import * as secure from "./secure";
import { useModel } from "./useModel";
import Assistant from "./Assistant";
import Code from "./code/Code";
import Desk from "./Desk";
import Research, { useResearch } from "./Research";
import Stories, { useStories } from "./Stories";
import StoryAccounts from "./StoryAccounts";
import Music from "./Music";
import Social from "./Social";
import { PortalOverlay, usePortal } from "./Portal";
import { Clips, Live, Log, SettingsTab, SignIn, Studio } from "./Remote";
import { Button, C, Card, Icon, IconButton, Pill, t } from "./theme";
import { isNewerVersion, releaseVersion } from "./updates";

const POLL_MS = 6000;
const RELEASE_API = "https://api.github.com/repos/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/tags/phone-latest";
const RELEASE_PAGE = "https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/tag/phone-latest";
const CLIP_TABS = [["desk", "Desk", "albums"], ["research", "Research", "search"]];
const STORY_TABS = [["stories", "Create", "moon"], ["story-library", "Library", "albums"], ["story-publishing", "Publishing", "send"], ["story-accounts", "Accounts", "people"], ["story-settings", "Settings", "settings"]];
const MUSIC_TABS = [["music", "Create", "musical-notes"], ["music-library", "Library", "albums"], ["music-production", "Production", "options"], ["music-settings", "Settings", "settings"]];
const SOCIAL_TABS = [["social", "Clients", "people"], ["social-content", "Content", "create"], ["social-calendar", "Calendar", "calendar"], ["social-assets", "Assets", "images"], ["social-profiles", "Profiles", "link"], ["social-settings", "Settings", "settings"]];
const BUSINESS = [["clips", "Surge", "Streamer clips", CLIP_TABS], ["stories", "Hollow", "Scary stories", STORY_TABS], ["music", "Resonance", "Music production", MUSIC_TABS], ["social", "Social Studio", "Client content", SOCIAL_TABS]];
const businessFor = key => BUSINESS.find(([, , , tabs]) => tabs.some(([tab]) => tab === key))?.[0];
const isMusic = key => businessFor(key) === "music";
const isSocial = key => businessFor(key) === "social";
const isStory = key => key === "stories" || key.startsWith("story-");
const DESK_TABS = [["today", "Today"], ["live", "Live"], ["clips", "Clips"], ["studio", "Studio"], ["settings", "Settings"], ["log", "Log"]];

/* The same releases the sideloaders read. AltStore updates by itself once its source is added;
   this banner is for everyone else (and Android, where you tap and install). */
function useUpdate(current) {
  const [latest, setLatest] = useState("");
  useEffect(() => {
    let alive = true;
    fetch(RELEASE_API).then(r => r.json()).then(d => {
      const found = releaseVersion(d);
      if (alive && isNewerVersion(found, current)) setLatest(found);
    }).catch(() => {});
    return () => { alive = false; };
  }, [current]);
  return latest;
}

export default function App() {
  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      <Main />
    </View>);
}

function Main() {
  const [host, setHost] = useState(null);
  const [token, setToken] = useState(null);
  const [ready, setReady] = useState(false);
  const [state, setState] = useState({});
  const portal = usePortal("desk");
  const { tab, navigate } = portal;
  const [business, setBusiness] = useState("clips");
  const remembered = useRef({ clips: "desk", stories: "stories", music: "music", social: "social" });
  const [businessStates, setBusinessStates] = useState([]), [businessError, setBusinessError] = useState(""), [runtimeBusy, setRuntimeBusy] = useState(false);
  const storyEdits = useRef(false);
  const onStoryDirty = useCallback(value => { storyEdits.current = value; }, []);
  const setTab = useCallback(next => {
    const go = () => {
      if (businessFor(next)) {
        const target = businessFor(next);
        remembered.current[target] = next; setBusiness(target);
      }
      navigate(next);
    };
    const unmountsEditor = businessFor(next) !== businessFor(tab) || isStory(tab) || [tab, next].some(key => ["music-settings", "social-settings"].includes(key));
    if (next !== tab && unmountsEditor && storyEdits.current) {
      if (Platform.OS === "web") {
        if (globalThis.confirm("Leave without saving your workspace edits?")) { storyEdits.current = false; go(); }
        return;
      }
      Alert.alert("Leave without saving?", "Your workspace edits have not been saved to the PC.", [
        { text: "Keep editing", style: "cancel" },
        { text: "Discard edits", style: "destructive", onPress: () => { storyEdits.current = false; go(); } },
      ]);
    } else go();
  }, [tab, navigate]);
  const [deskTab, setDeskTab] = useState("today");
  const [offline, setOffline] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [note, setNote] = useState("");
  const [foreground, setForeground] = useState(AppState.currentState !== "background" && AppState.currentState !== "inactive");
  const [loaded, setLoaded] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const flight = useRef(null);
  const session = useRef(null);
  const currentSession = `${host || ""}:${token || ""}`;
  session.current = currentSession;
  const toast = (msg) => { setNote(msg); setTimeout(() => setNote(""), 2600); };
  const update = useUpdate(Constants.expoConfig?.version || "");
  const lock = useLock();
  const modelEnabled = useRef(false);
  if (["chat", "code"].includes(tab)) modelEnabled.current = true;
  const m = useModel({ host, token, enabled: modelEnabled.current });
  useEffect(() => {
    const subscription = AppState.addEventListener("change", next => setForeground(next === "active"));
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    (async () => {
      const [h, tk] = await Promise.all([secure.get(KEY_HOST), secure.get(KEY_TOKEN)]);
      if (h && tk) { setHost(h); setToken(tk); }
      setReady(true);
    })();
  }, []);

  const signOut = useCallback(async (expired = false) => {
    await secure.del(KEY_TOKEN);
    setToken(null); setState({}); setLoaded(false); setSignedOut(expired);
  }, []);
  const onError = useCallback(() => setOffline(true), []);

  const poll = useCallback(() => {
    if (!host || !token) return Promise.resolve();
    if (flight.current?.key === currentSession) return flight.current.promise;
    const promise = (async () => {
      try {
        const r = await call(host, "/api/state", { token });
        if (session.current !== currentSession) return;
        if (r.status === 401) { await signOut(true); return; }
        if (!r.ok) throw new Error(`The PC answered ${r.status}`);
        setState(r.data); setOffline(false); setLoaded(true);
      } catch (e) { if (session.current === currentSession) setOffline(true); }
      finally { if (flight.current?.promise === promise) flight.current = null; }
    })();
    flight.current = { key: currentSession, promise };
    return promise;
  }, [host, token, signOut, currentSession]);

  const loadBusinesses = useCallback(async () => {
    if (!host || !token) return;
    const r = await call(host, "/api/businesses", { token });
    if (r.status === 401) { await signOut(true); return; }
    if (!r.ok) throw new Error(typeof r.data?.detail === "string" ? r.data.detail : "Business controls could not load. Pull down or retry.");
    if (session.current !== currentSession) return;
    setBusinessStates(r.data.businesses || []); setBusinessError("");
  }, [host, token, currentSession, signOut]);
  useEffect(() => { setBusinessStates([]); setBusinessError(""); }, [host, token]);
  useEffect(() => {
    if (!host || !token || !foreground || lock.locked) return;
    let alive = true, timer;
    const tick = async () => { try { await loadBusinesses(); } catch (e) { if (alive) setBusinessError(e.message); } if (alive) timer = setTimeout(tick, POLL_MS); };
    tick(); return () => { alive = false; clearTimeout(timer); };
  }, [host, token, foreground, lock.locked, loadBusinesses]);
  const toggleBusiness = async () => {
    const current = businessStates.find(row => row.id === business); if (!current || runtimeBusy) return;
    setRuntimeBusy(true); setBusinessError("");
    try {
      const r = await call(host, `/api/businesses/${business}`, { token, method: "POST", body: { enabled: !current.enabled }, timeout: 65000 });
      if (r.status === 401) { await signOut(true); return; }
      if (!r.ok || r.data?.ok === false) throw new Error(r.data?.detail || "Business control failed. Retry.");
      setBusinessStates(r.data.businesses || []);
    } catch (e) { setBusinessError(e.message); } finally { setRuntimeBusy(false); }
  };

  const research = useResearch({ host, token, active: foreground && !lock.locked && ["desk", "research"].includes(tab), onUnauthorized: signOut });
  const stories = useStories({ host, token, active: foreground && !lock.locked && isStory(tab), onUnauthorized: signOut });

  useEffect(() => {
    if (!host || !token || !foreground || lock.locked || !["desk", "research"].includes(tab)) return undefined;
    let alive = true, timer;
    const tick = async () => { await poll(); if (alive) timer = setTimeout(tick, POLL_MS); };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [host, token, poll, tab, foreground, lock.locked]);

  const pause = async () => {
    setBusy(true);
    try {
      const r = await call(host, state.manual_paused ? "/api/control/resume" : "/api/control/pause", { token, method: "POST" });
      if (!r.ok) { if (r.status === 401) await signOut(true); throw new Error("Capture control failed"); }
      await poll();
    } catch (e) { setOffline(true); }
    setBusy(false);
  };

  if (!ready) return <View style={{ flex: 1, backgroundColor: C.bg, justifyContent: "center" }}><ActivityIndicator color={C.ink2} /></View>;
  if (lock.locked) {
    return (
      <SafeAreaProvider>
        <StatusBar barStyle="light-content" backgroundColor={C.bg} />
        <LockScreen onUnlock={lock.unlock} problem={lock.problem} />
      </SafeAreaProvider>);
  }

  const linked = !!(host && token);
  const connection = !linked ? ["Not connected", "plain"] : offline ? ["Can't reach PC", "bad"] : !loaded ? ["Connecting", "plain"] : ["Connected", "good"];
  const selectedBusiness = BUSINESS.find(([id]) => id === business);
  const runtime = businessStates.find(row => row.id === business);
  const TABS = [...selectedBusiness[3], ["tools", "Tools", "grid"]];
  const remoteTab = !!businessFor(tab);
  const title = tab === "chat" ? "Assistant" : tab === "code" ? "Code" : TABS.find(x => x[0] === tab)?.[1] || "Desk";

  return (
    <SafeAreaProvider>
      <Animated.View style={portal.shellStyle}>
      <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }} edges={["top"]}>
        <StatusBar barStyle="light-content" backgroundColor={C.bg} />
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingTop: 6, paddingBottom: 12 }}>
          <Image source={require("./assets/icon.png")} resizeMode="contain" style={{ width: 28, height: 28 }} />
          <View style={{ flex: 1 }}><Text style={t.h2}>Ashvane</Text><Text style={t.faint}>{selectedBusiness[1]} · {title}</Text></View>
          {remoteTab && <Pill label={!linked ? "Not connected" : businessError ? "Check PC" : businessStates.length ? "Connected" : "Connecting"} tone={!linked || !businessStates.length ? "plain" : businessError ? "bad" : "good"} />}
          {remoteTab && linked && <IconButton icon="log-out-outline" label="Sign out" onPress={() => signOut(false)} />}
        </View>

        <View accessibilityRole="tablist" style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, paddingHorizontal: 16, paddingBottom: 10 }}>
          {BUSINESS.map(([key, name, description]) => <Pressable key={key} accessibilityRole="button" accessibilityLabel={`${name} · ${description}`} accessibilityState={{ selected: business === key }} aria-selected={business === key} onPress={() => setTab(remembered.current[key])} style={({ pressed }) => ({ width: "48%", flexGrow: 1, minHeight: 54, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 7, borderWidth: 1, borderColor: business === key ? C.ember : C.line, backgroundColor: business === key ? C.emberSoft : C.s1, opacity: pressed ? 0.7 : 1 })}><Text style={[t.body, { fontWeight: "600", color: business === key ? C.ember : C.ink }]}>{name}</Text><Text style={t.faint}>{description}</Text></Pressable>)}
        </View>
        {remoteTab && linked && <View style={{ flexDirection: "row", gap: 12, alignItems: "center", paddingHorizontal: 16, paddingBottom: 10 }}><View style={{ flex: 1 }}><Text accessibilityLiveRegion="polite" style={t.faint}>{runtime?.message || "Checking business runtime…"}</Text>{runtime?.busy && !runtime.message && <Text style={t.faint}>{runtime.enabled ? "Work in progress" : "Stopping · current work is finishing"}</Text>}</View><Button small label={`${runtime?.enabled ? "Stop" : "Start"} ${selectedBusiness[1]}`} busy={runtimeBusy} disabled={!runtime || (!runtime.enabled && runtime.busy)} onPress={toggleBusiness} /></View>}
        {!!businessError && remoteTab && <Banner tone="bad" text={businessError} onPress={() => loadBusinesses().catch(e => setBusinessError(e.message))} />}
        {!!note && <Banner tone="plain" text={note} />}
        {!!update && <Banner tone="live" text={`Version ${update} is out · tap to get it`} onPress={() => Linking.openURL(RELEASE_PAGE)} />}

        <View style={{ flex: 1 }}>
          {remoteTab && (!linked ? (
            <>
              {signedOut && <Banner tone="plain" text="The PC ended the session. Sign in again below." />}
              <SignIn onDone={(h, tk) => { setHost(h); setToken(tk); setSignedOut(false); setOffline(false); }} />
            </>
          ) : (
            <>
              {businessFor(tab) === "clips" && offline && <Banner tone="bad" text="Can't reach the PC. Pull down to retry, or open Live → Test." />}
              {isStory(tab) && !["story-accounts", "story-settings"].includes(tab) && <Stories screen={tab} studio={stories} host={host} token={token} onUnauthorized={signOut} onDirtyChange={onStoryDirty} />}
              {tab === "story-accounts" && <StoryAccounts host={host} token={token} onUnauthorized={signOut} onChanged={stories.load} onDirtyChange={onStoryDirty} />}
              {tab === "story-settings" && <ScrollView contentContainerStyle={{ padding: 16 }}><SettingsTab onlySections={["stories"]} host={host} token={token} toast={toast} onError={onError} /></ScrollView>}
              {isMusic(tab) && tab !== "music-settings" && <Music screen={tab} host={host} token={token} onUnauthorized={signOut} onDirtyChange={onStoryDirty} active={foreground && !lock.locked} runtime={runtime} />}
              {tab === "music-settings" && <ScrollView contentContainerStyle={{ padding: 16 }}><SettingsTab onlySections={["music"]} host={host} token={token} toast={toast} onError={onError} /></ScrollView>}
              {tab === "social-settings" && <ScrollView contentContainerStyle={{ padding: 16 }}><SettingsTab onlySections={["social"]} host={host} token={token} toast={toast} onError={onError} /></ScrollView>}
              {isSocial(tab) && tab !== "social-settings" && <Social screen={tab} host={host} token={token} onUnauthorized={signOut} onDirtyChange={onStoryDirty} active={foreground && !lock.locked} runtime={runtime} />}
              {tab === "desk" && <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, flexShrink: 0, height: 56 }}
                contentContainerStyle={{ paddingHorizontal: 16, gap: 8, paddingBottom: 12 }}>
                {DESK_TABS.map(([key, label]) => {
                  const on = key === deskTab;
                  return (
                    <Pressable key={key} onPress={() => setDeskTab(key)} accessibilityRole="tab" accessibilityState={{ selected: on }} aria-selected={on}
                      style={({ pressed }) => ({ minHeight: 44, paddingHorizontal: 14, borderRadius: 10, justifyContent: "center", opacity: pressed ? 0.7 : 1,
                        backgroundColor: on ? C.ink : C.s1, borderWidth: 1, borderColor: on ? C.ink : C.line })}>
                      <Text style={{ fontSize: 14, fontWeight: "600", color: on ? C.bg : C.ink2 }}>{label}</Text>
                    </Pressable>);
                })}
              </ScrollView>}
              {businessFor(tab) === "clips" && <ScrollView contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 30 }}
                refreshControl={<RefreshControl tintColor={C.ink2} refreshing={refreshing}
                  onRefresh={async () => { setRefreshing(true); try { await Promise.all([poll(), research.load()]); setRefreshVersion(v => v + 1); } finally { setRefreshing(false); } }} />}>
                {tab === "research" ? <Research research={research} /> : <>
                  {deskTab === "today" && <Desk state={state} research={research.data} loaded={loaded} busy={busy} onPause={pause} onNavigate={setDeskTab} onResearch={() => setTab("research")} />}
                  {deskTab === "live" && <Live state={state} onPause={pause} busy={busy} host={host} token={token} />}
                  {deskTab === "clips" && <Clips host={host} token={token} state={state} toast={toast} refreshVersion={refreshVersion} onError={onError} />}
                  {deskTab === "studio" && <Studio key={refreshVersion} host={host} token={token} toast={toast} onError={onError} />}
                  {deskTab === "settings" && <SettingsTab excludeSections={["stories", "story_accounts", "music", "social", "businesses"]} key={refreshVersion} host={host} token={token} toast={toast} onError={onError} />}
                  {deskTab === "log" && <Log key={refreshVersion} host={host} token={token} state={state} onError={onError} />}
                </>}
              </ScrollView>}
            </>))}
          {tab === "chat" && <Assistant host={host} token={token} m={m} onError={onError} />}
          {tab === "code" && <Code m={m} />}
          {tab === "tools" && <ScrollView contentContainerStyle={{ padding: 16, gap: 16 }}><Card><Text style={t.h2}>Optional workspace tools</Text><Text style={[t.muted, { marginTop: 6, marginBottom: 16 }]}>A private assistant and code workspace are available when you need them.</Text><Button label="Open Assistant" icon="chatbubble-ellipses-outline" onPress={() => setTab("chat")} /><Button label="Open Code" icon="code-slash-outline" onPress={() => setTab("code")} style={{ marginTop: 10 }} /></Card></ScrollView>}
        </View>

        <SafeAreaView edges={["bottom"]} style={{ backgroundColor: C.s1, borderTopWidth: 1, borderTopColor: C.line }}>
          <ScrollView horizontal showsHorizontalScrollIndicator={business === "social"} contentContainerStyle={{ flexGrow: 1, flexDirection: "row", paddingTop: 6 }}>
            {TABS.map(([key, label, icon]) => {
              const on = key === tab || (key === "tools" && ["chat", "code"].includes(tab));
              return (
                <Pressable key={key} onPress={() => setTab(key)} accessibilityRole="tab" accessibilityLabel={label} accessibilityState={{ selected: on }} aria-selected={on}
                  style={{ flex: 1, minWidth: business === "social" ? 60 : 0, alignItems: "center", paddingVertical: 6, gap: 3 }}>
                  <View style={{ width: 22, height: 3, borderRadius: 2, marginBottom: 3, backgroundColor: on ? C.ember : "transparent" }} />
                  <Icon name={on ? icon : `${icon}-outline`} size={22} color={on ? C.ink : C.ink3} />
                  <Text style={{ fontSize: 10.5, fontWeight: "600", color: on ? C.ink : C.ink3 }}>{label}</Text>
                </Pressable>);
            })}
          </ScrollView>
        </SafeAreaView>
      </SafeAreaView>
      </Animated.View>
      <PortalOverlay portal={portal} />
    </SafeAreaProvider>);
}

function Banner({ text, tone, onPress }) {
  const colors = { bad: [C.badSoft, "rgba(236,91,82,0.35)", C.ink], live: [C.emberSoft, C.emberLine, C.ink], plain: [C.s2, C.line, C.ink] }[tone];
  return (
    <Pressable onPress={onPress} disabled={!onPress}
      style={{ marginHorizontal: 16, marginBottom: 10, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 12,
        backgroundColor: colors[0], borderWidth: 1, borderColor: colors[1] }}>
      <Text style={[t.muted, { color: colors[2] }]}>{text}</Text>
    </Pressable>);
}
