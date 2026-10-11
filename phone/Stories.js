import React, { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, Switch, Text, View } from "react-native";
import * as FileSystem from "expo-file-system";
import { WebView } from "react-native-webview";
import { call } from "./api";
import { Button, C, Card, Empty, Field, MONO, Pill, Section, t } from "./theme";
import Learning from "./Learning";

const POLL_MS = 6000;
const text = value => typeof value === "string" ? value : value == null ? "" : JSON.stringify(value);
const problem = r => text(r.data?.detail || r.data?.error) || `The PC answered ${r.status}. Try again.`;
const projectPath = id => `/api/stories/projects/${encodeURIComponent(id)}`;
const activeStates = new Set(["queued", "directing", "writing", "judging", "narrating", "rendering"]);
const errorList = value => Array.isArray(value) ? value.map(text) : Object.entries(value || {}).map(([key, message]) => `${key}: ${text(message)}`);
const visualOptions = {
  setting: [["corridor", "Corridor"], ["forest", "Forest"], ["street", "Street"], ["room", "Room"], ["station", "Station"]],
  subject: [["figure", "Figure"], ["creature", "Creature"], ["none", "No figure"]],
  action: [["approach", "Approach"], ["reveal", "Reveal"], ["vanish", "Vanish"], ["follow", "Follow"], ["wait", "Wait"]],
};

export function useStories({ host, token, active, onUnauthorized }) {
  const [data, setData] = useState(null), [publishing, setPublishing] = useState(null);
  const [error, setError] = useState(""), [loading, setLoading] = useState(false);
  const session = useRef(""), flight = useRef(null), controllers = useRef(new Set());
  const key = `${host || ""}:${token || ""}`; session.current = key;
  const send = useCallback(async (path, options = {}) => {
    const controller = new AbortController(); controllers.current.add(controller);
    try {
      const r = await call(host, path, { token, ...options, signal: controller.signal });
      if (session.current !== key) throw new Error("The sign-in changed. Reopen Stories.");
      if (r.status === 401) { onUnauthorized(true); throw new Error("Sign in again to continue."); }
      if (!r.ok || r.data?.ok === false) throw new Error(problem(r));
      return r.data;
    } finally { controllers.current.delete(controller); }
  }, [host, token, key, onUnauthorized]);
  const load = useCallback(() => {
    if (!host || !token) return Promise.resolve();
    if (flight.current?.key === key) return flight.current.promise;
    setLoading(true);
    const promise = (async () => {
      try {
        const [studio, publisher] = await Promise.all([send("/api/stories"), send("/api/stories/publishing")]);
        if (session.current === key) { setData(studio); setPublishing(publisher); setError(""); }
      } catch (e) { if (session.current === key && e.name !== "AbortError") setError(e.message || "Stories did not answer. Check the PC connection."); }
      finally { if (flight.current?.promise === promise) flight.current = null; if (session.current === key) setLoading(false); }
    })();
    flight.current = { key, promise }; return promise;
  }, [host, token, key, send]);
  useEffect(() => { setData(null); setPublishing(null); setError(""); return () => { controllers.current.forEach(c => c.abort()); controllers.current.clear(); }; }, [host, token]);
  useEffect(() => {
    if (!active || !host || !token) { controllers.current.forEach(c => c.abort()); return; }
    let alive = true, timer;
    const tick = async () => { await load(); if (alive) timer = setTimeout(tick, POLL_MS); }; tick();
    return () => { alive = false; clearTimeout(timer); controllers.current.forEach(c => c.abort()); };
  }, [active, host, token, load]);
  const request = async (path, options) => { const result = await send(path, options); await load(); return result; };
  return { data, publishing, error, loading, load, request };
}

function Choices({ label, options, value, onChange, disabled = false }) {
  return <View style={{ gap: 8 }}><Text style={t.label}>{label}</Text><View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
    {options.map(([id, name]) => <Pressable key={id} accessibilityRole="radio" accessibilityLabel={name} accessibilityState={{ selected: value === id, disabled }} disabled={disabled} onPress={() => onChange(id)}
      style={({ pressed }) => ({ minHeight: 44, paddingHorizontal: 12, justifyContent: "center", borderWidth: 1, borderRadius: 6, borderColor: value === id ? C.ember : C.line, backgroundColor: value === id ? C.emberSoft : C.s2, opacity: pressed ? 0.7 : 1 })}>
      <Text style={[t.muted, { color: value === id ? C.ember : C.ink2 }]}>{name}</Text></Pressable>)}
  </View></View>;
}

function Publishing({ state, request, onError }) {
  const config = state?.config || {}, [saving, setSaving] = useState(false);
  const update = async change => {
    setSaving(true);
    try { await request("/api/stories/publishing", { method: "PUT", body: { ...config, ...change } }); }
    catch (e) { onError(e.message); } finally { setSaving(false); }
  };
  const selected = Array.isArray(config.destinations) ? config.destinations : [];
  return <Section title="Story publishing"><Card style={{ gap: 14 }}>
    <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}><View style={{ flex: 1 }}><Text style={t.h2}>Auto-publish completed stories</Text><Text style={[t.faint, { marginTop: 4 }]}>Uses these story destinations independently from Clips.</Text></View>
      <Switch accessibilityLabel="Auto-publish completed stories" value={!!config.enabled} disabled={!state || saving} onValueChange={enabled => update({ enabled })} trackColor={{ false: C.s4, true: C.emberLine }} thumbColor={config.enabled ? C.ember : C.ink2} /></View>
    {!state && <Text style={t.muted}>Loading connected destinations…</Text>}
    {(state?.destinations || []).map(d => <Pressable key={d.id} accessibilityRole="checkbox" accessibilityState={{ checked: selected.includes(d.id), disabled: saving }} disabled={saving} onPress={() => update({ destinations: selected.includes(d.id) ? selected.filter(id => id !== d.id) : [...selected, d.id] })}
      style={({ pressed }) => ({ paddingVertical: 10, borderTopWidth: 1, borderTopColor: C.line, opacity: pressed ? 0.7 : 1, gap: 4 })}>
      <View style={{ flexDirection: "row", gap: 8 }}><Text style={[t.body, { flex: 1 }]}>{selected.includes(d.id) ? "✓ " : "○ "}{d.label || d.id}</Text><Pill label={d.ready ? "Connected" : "Setup needed"} tone={d.ready ? "good" : "plain"} /></View>
      {!!d.account_label && <Text style={t.faint}>{d.account_label}</Text>}{!!d.reason && <Text style={t.faint}>{d.reason}</Text>}
    </Pressable>)}
    <Choices label="YouTube visibility" options={[["private", "Private"], ["unlisted", "Unlisted"], ["public", "Public"]]} value={config.privacy || "private"} disabled={!state || saving} onChange={privacy => update({ privacy })} />
    {saving && <Text accessibilityLiveRegion="polite" style={t.faint}>Saving publishing preferences…</Text>}
    {!!config.enabled && !selected.length && <Text style={t.error}>Choose at least one destination for auto-publishing.</Text>}
    {errorList(state?.errors).map((e, i) => <Text key={i} style={t.error}>{e}</Text>)}
  </Card></Section>;
}

function Preview({ host, token, project, onClose, onUnauthorized }) {
  const [uri, setUri] = useState(""), [error, setError] = useState("");
  useEffect(() => {
    let alive = true, downloader, blobUrl, directory, ctrl = new AbortController();
    const prepare = async () => {
      try {
        const remote = `${host}${projectPath(project.id)}/video`;
        if (Platform.OS === "web") {
          const response = await fetch(remote, { headers: { Authorization: `Bearer ${token}` }, signal: ctrl.signal });
          if (response.status === 401) { onUnauthorized(true); throw new Error("Sign in again to preview."); }
          if (!response.ok) throw new Error(`Preview download failed (${response.status}).`);
          blobUrl = URL.createObjectURL(await response.blob()); if (alive) setUri(blobUrl);
        } else {
          directory = `${FileSystem.cacheDirectory}story-preview-${Date.now()}-${Math.random().toString(36).slice(2)}/`;
          await FileSystem.makeDirectoryAsync(directory, { intermediates: true });
          if (!alive) return;
          downloader = FileSystem.createDownloadResumable(remote, `${directory}story.mp4`, { headers: { Authorization: `Bearer ${token}`, "X-ClipBot": "1" } });
          const result = await downloader.downloadAsync();
          if (result?.status === 401) { onUnauthorized(true); throw new Error("Sign in again to preview."); }
          if (!result || result.status !== 200) throw new Error("The video could not be downloaded. Retry when the PC is connected.");
          if (!alive) return;
          await FileSystem.writeAsStringAsync(`${directory}index.html`, '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{margin:0;background:#070a10;height:100%;display:grid;place-items:center}video{width:100%;max-height:100vh}</style></head><body><video controls playsinline src="story.mp4"></video></body></html>');
          if (alive) setUri(`${directory}index.html`);
        }
      } catch (e) { if (alive && e.name !== "AbortError") setError(e.message || "Preview could not be loaded."); }
      finally { if (!alive && directory) await FileSystem.deleteAsync(directory, { idempotent: true }).catch(() => {}); }
    };
    prepare();
    return () => {
      alive = false; ctrl.abort(); if (blobUrl) URL.revokeObjectURL(blobUrl);
      (async () => { if (downloader) await downloader.pauseAsync().catch(() => {}); if (directory) await FileSystem.deleteAsync(directory, { idempotent: true }).catch(() => {}); })();
    };
  }, [host, token, project.id, project.updated_at, onUnauthorized]);
  return <Card style={{ gap: 12 }}><Text style={t.h2}>Final video</Text>
    {!!error && <Text style={t.error}>{error}</Text>}
    {!uri && !error && <><ActivityIndicator color={C.ember} /><Text style={t.faint}>Downloading a private preview to this phone…</Text></>}
    {!!uri && (Platform.OS === "web" ? React.createElement("video", { src: uri, controls: true, style: { width: "100%", maxHeight: 440 } }) : <WebView style={{ height: 420, backgroundColor: C.bg }} source={{ uri }} originWhitelist={["file://*"]} allowingReadAccessToURL={uri.replace(/index\.html$/, "")} allowFileAccess allowFileAccessFromFileURLs allowsInlineMediaPlayback
      onShouldStartLoadWithRequest={r => r.url.startsWith("file://") || r.url === "about:blank"} onError={() => setError("This phone could not open the downloaded video.")} />)}
    <Button label="Close preview" onPress={onClose} />
  </Card>;
}

const projectBuffers = new Map();
function Project({ project, request, host, token, publishing, onUnauthorized, onError, onDirtyChange, workspaceActive }) {
  const bufferKey = `${host}:${token}:${project.id}`, buffer = projectBuffers.get(bufferKey);
  const [open, setOpen] = useState(!!buffer), [preview, setPreview] = useState(false), [busy, setBusy] = useState("");
  const [title, setTitle] = useState(buffer?.title ?? project.title ?? ""), [script, setScript] = useState(buffer?.script ?? project.script ?? "");
  const [publicTitle, setPublicTitle] = useState(buffer?.publicTitle ?? project.public_copy?.youtube?.title ?? ""), [description, setDescription] = useState(buffer?.description ?? project.public_copy?.youtube?.description ?? "");
  const [sceneEdits, setSceneEdits] = useState(buffer?.sceneEdits ?? project.scenes ?? []);
  useEffect(() => { if (!workspaceActive) setPreview(false); }, [workspaceActive]);
  const [dirty, setDirty] = useState(!!buffer);
  useEffect(() => { if (dirty) projectBuffers.set(bufferKey, { title, script, publicTitle, description, sceneEdits }); else projectBuffers.delete(bufferKey); }, [bufferKey, dirty, title, script, publicTitle, description, sceneEdits]);
  useEffect(() => { onDirtyChange(project.id, dirty); return () => onDirtyChange(project.id, false); }, [dirty, project.id, onDirtyChange]);
  useEffect(() => {
    if (dirty) return;
    setTitle(project.title || ""); setScript(project.script || ""); setSceneEdits(project.scenes || []);
    setPublicTitle(project.public_copy?.youtube?.title || ""); setDescription(project.public_copy?.youtube?.description || "");
  }, [project.updated_at, dirty]);
  const edit = setter => value => { setter(value); setDirty(true); };
  const active = activeStates.has(project.status);
  const action = async (name, body) => {
    if (busy) return;
    setBusy(name);
    try { await request(`${projectPath(project.id)}${name === "save" ? "" : `/${name}`}`, { method: name === "save" ? "PUT" : "POST", ...(body ? { body } : {}) }); if (name === "save") setDirty(false); }
    catch (e) { onError(e.message); } finally { setBusy(""); }
  };
  const save = () => action("save", { title, script, ...(script === project.script ? { scenes: sceneEdits } : {}), public_copy: { ...project.public_copy, youtube: { ...project.public_copy?.youtube, title: publicTitle, description } } });
  const remove = () => {
    const message = `Delete “${project.title || "Untitled story"}” and its production files? Published posts will stay online.`;
    const confirm = async () => { try { await request(projectPath(project.id), { method: "DELETE" }); } catch (e) { onError(e.message); } };
    if (Platform.OS === "web") { if (globalThis.confirm(message)) confirm(); }
    else Alert.alert("Delete story?", message, [{ text: "Keep", style: "cancel" }, { text: "Delete", style: "destructive", onPress: confirm }]);
  };
  const records = Array.isArray(project.publishing) ? project.publishing : Object.entries(project.publishing || project.publications || {}).map(([platform, record]) => ({ platform, ...record }));
  return <Card style={{ marginBottom: 16 }}>
    <Pressable accessibilityRole="button" accessibilityState={{ expanded: open }} onPress={() => setOpen(!open)} style={({ pressed }) => ({ minHeight: 44, opacity: pressed ? 0.7 : 1, gap: 8 })}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}><Text style={[t.h2, { flex: 1 }]}>{project.title || project.topic || "Untitled story"}</Text><Pill label={(project.status || "draft").replace(/_/g, " ")} tone={project.status === "ready" ? "good" : project.status === "failed" ? "bad" : active ? "live" : "plain"} /></View>
      <Text style={t.faint}>{project.genre?.replace(/_/g, " ")} · {project.format === "animated" ? "Animated" : "Illustrated"} · {Math.round(project.duration_s || 0)}s</Text>
    </Pressable>
    {active && <View style={{ marginTop: 12, gap: 8 }}><View style={{ height: 3, backgroundColor: C.s4 }}><View style={{ height: 3, width: `${Math.max(0, Math.min(1, Number(project.progress) || 0)) * 100}%`, backgroundColor: C.ember }} /></View><Text accessibilityLiveRegion="polite" style={t.faint}>{project.status} · {Math.round((Number(project.progress) || 0) * 100)}%</Text><Button small label="Cancel production" busy={busy === "cancel"} onPress={() => action("cancel")} /></View>}
    {!!project.error && <Text style={[t.error, { marginTop: 12 }]}>{text(project.error)}</Text>}
    {open && <View style={{ gap: 16, marginTop: 20 }}>
      {!!project.review && <View style={{ gap: 6, borderLeftWidth: 2, borderLeftColor: project.review.passed ? C.good : C.ember, paddingLeft: 12 }}><Text style={t.label}>Private story review · {project.review.passed ? "Passed" : "Needs review"}</Text><Text style={t.muted}>{text(project.review.reason)}</Text>{(project.review.issues || []).map((issue, i) => <Text key={i} style={t.faint}>{text(issue)}</Text>)}</View>}
      <Field label="Project title" value={title} editable={!active && !busy} onChangeText={edit(setTitle)} maxLength={100} />
      <Field label="Narrated manuscript" value={script} multiline editable={!active && !busy} onChangeText={edit(setScript)} inputStyle={{ minHeight: 220, fontFamily: Platform.OS === "ios" ? "Georgia" : "serif", lineHeight: 25 }} />
      {script !== project.script && <Text style={t.faint}>Saving a revised manuscript rebuilds its scenes. Save it before adjusting scene direction.</Text>}
      {!!sceneEdits.length && <View style={{ gap: 12 }}><Text style={t.label}>Scene direction</Text>{sceneEdits.map((scene, i) => <View key={scene.id || i} style={{ gap: 12, borderTopWidth: 1, borderTopColor: C.line, paddingTop: 10 }}>
        <Text style={[t.faint, { fontFamily: MONO }]}>SCENE {String(i + 1).padStart(2, "0")}</Text><Text style={t.muted}>{scene.narration}</Text>
        {Object.entries(visualOptions).map(([property, options]) => <Choices key={property} label={`Stage ${property}`} options={options} value={scene.visual?.[property] || options[0][0]} disabled={active || !!busy || script !== project.script}
          onChange={value => { setSceneEdits(items => items.map((s, index) => index === i ? { ...s, visual: { setting: "corridor", subject: "figure", action: "approach", ...s.visual, [property]: value } } : s)); setDirty(true); }} />)}
        <Field label="Illustration direction" value={scene.visual_prompt || ""} multiline editable={!active && !busy && script === project.script} onChangeText={value => { setSceneEdits(items => items.map((s, index) => index === i ? { ...s, visual_prompt: value } : s)); setDirty(true); }} />
        <Text style={t.faint}>Stage controls drive the shadow-theatre render. Illustration direction describes the scene for an image provider.</Text>
      </View>)}</View>}
      <View style={{ gap: 12, paddingTop: 16, borderTopWidth: 1, borderTopColor: C.line }}><Text style={t.h2}>Public YouTube copy</Text><Field label="Video title" value={publicTitle} maxLength={100} editable={!active && !busy} onChangeText={edit(setPublicTitle)} /><Field label="Description" value={description} multiline maxLength={5000} editable={!active && !busy} onChangeText={edit(setDescription)} /><Text style={t.faint}>{(project.public_copy?.youtube?.hashtags || []).join(" ")}</Text></View>
      {dirty && <Text style={t.faint}>Unsaved changes. Saving clears the previous approval and render; review the revised story before production.</Text>}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
        <Button label="Save changes" disabled={!dirty || active || !!busy} busy={busy === "save"} onPress={save} />
        <Button label="Review story" disabled={dirty || active || !!busy || !script} busy={busy === "review"} onPress={() => action("review")} />
        <Button label="Render video" kind="primary" disabled={dirty || active || !!busy || !project.review?.passed} busy={busy === "render"} onPress={() => action("render")} />
        {["failed", "interrupted"].includes(project.status) && <Button label="Retry production" disabled={dirty || !!busy} busy={busy === "retry"} onPress={() => action("retry")} />}
        {!!project.video_url && <Button label={preview ? "Hide video" : "Preview video"} disabled={dirty || active} onPress={() => setPreview(!preview)} />}
        <Button label="Publish now" disabled={dirty || active || !!busy || !project.video_url || !project.review?.passed || !publishing?.config?.destinations?.length} busy={busy === "publish"} onPress={() => action("publish", { destinations: publishing.config.destinations })} />
        <Button label="Delete story" kind="danger" disabled={active || !!busy} onPress={remove} />
      </View>
      {!project.review?.passed && <Text style={t.faint}>A passing story review is required before rendering and publishing.</Text>}
      {!!records.length && <View style={{ gap: 8 }}><Text style={t.label}>Publishing history</Text>{records.map((r, i) => <View key={`${r.platform}-${i}`}><Text style={t.muted}>{r.platform || r.destination} · {r.status || "pending"}</Text>{!!r.error && <Text style={t.error}>{text(r.error)}</Text>}{!!r.url && <Text selectable style={t.faint}>{r.url}</Text>}</View>)}</View>}
      {preview && !dirty && <Preview host={host} token={token} project={project} onClose={() => setPreview(false)} onUnauthorized={onUnauthorized} />}
    </View>}
  </Card>;
}

export default function Stories({ screen = "stories", studio, host, token, onUnauthorized, onDirtyChange, active = true }) {
  const { data, publishing, error, loading, load, request } = studio;
  const [topic, setTopic] = useState(""), [genre, setGenre] = useState("paranormal"), [format, setFormat] = useState("still"), [duration, setDuration] = useState("60"), [voice, setVoice] = useState("");
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(""), [failure, setFailure] = useState("");
  const [topicMode, setTopicMode] = useState("generated"), [direction, setDirection] = useState(""), [generatedTopic, setGeneratedTopic] = useState(""), [ideas, setIdeas] = useState([]);
  const [ideaProfile, setIdeaProfile] = useState(""), [selectedIdeaProfile, setSelectedIdeaProfile] = useState("");
  const initialized = useRef(false), formEdits = useRef(false), learningEdits = useRef(false);
  const edited = useRef(new Set());
  const reportDirty = useCallback(() => onDirtyChange?.({ dirty: formEdits.current || learningEdits.current || edited.current.size > 0, persistent: edited.current.size === 0 }), [onDirtyChange]);
  const projectDirty = useCallback((id, dirty) => { if (dirty) edited.current.add(id); else edited.current.delete(id); reportDirty(); }, [reportDirty]);
  const memoryDirty = useCallback(value => { learningEdits.current = value; reportDirty(); }, [reportDirty]);
  const editForm = setter => value => { setter(value); formEdits.current = true; reportDirty(); };
  const suggest = async () => {
    setBusy(true); setFailure("");
    try { const result = await request("/api/stories/ideas", { method: "POST", timeout: 300000, body: { genre, format, duration_s: Number(duration), direction } }); setIdeas(result.ideas || []); setIdeaProfile(result.account_profile_id || ""); }
    catch (e) { setFailure(e.message); } finally { setBusy(false); }
  };
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  useEffect(() => { if (data && !initialized.current) { initialized.current = true; setGenre(data.settings?.default_genre || "paranormal"); setFormat(data.settings?.default_format || "still"); setDuration(String(data.settings?.default_duration_s || 60)); } }, [data]);
  const create = async () => {
    const seconds = Number(duration), min = data?.settings?.min_duration_s || 30, max = data?.settings?.max_duration_s || 900;
    if ((topicMode === "given" && !topic.trim()) || !Number.isFinite(seconds) || seconds < min || seconds > max) { setFailure(`Enter a premise and a duration from ${min} to ${max} seconds.`); return; }
    setBusy(true); setFailure(""); setNotice("");
    try { await request("/api/stories/projects", { method: "POST", timeout: 300000, body: { topic_mode: topicMode, topic: (topicMode === "given" ? topic : generatedTopic).trim(), direction: topicMode === "generated" ? direction : "", genre, format, duration_s: seconds, voice } }); formEdits.current = false; reportDirty(); setNotice("Story production started on your PC. You can leave this screen while it works."); }
    catch (e) { setFailure(e.message); } finally { setBusy(false); }
  };
  const capabilities = data?.capabilities || {};
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 16, paddingBottom: 36 }}>
    <View style={{ marginTop: 8, marginBottom: 28, gap: 8, borderLeftWidth: 2, borderLeftColor: C.ember, paddingLeft: 14 }}><Text style={[t.faint, { fontFamily: MONO, letterSpacing: 1.5 }]}>ASHVANE / STORY OBSERVATORY</Text><Text style={[t.title, { fontSize: 30 }]}>Make the dark speak.</Text><Text style={t.muted}>Original horror, narrated and produced on your PC.</Text></View>
    {!!(error || failure) && <Card style={{ marginBottom: 16, gap: 12 }}><Text accessibilityRole="alert" style={t.error}>{failure || error}</Text><Button label="Retry connection" busy={loading} onPress={load} /></Card>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={[t.muted, { marginBottom: 16 }]}>{notice}</Text>}
    {!data && loading && <ActivityIndicator accessibilityLabel="Loading story studio" color={C.ember} style={{ marginBottom: 16 }} />}
    {screen === "stories" && <Section title="New production"><Card style={{ gap: 20 }}>
      <Choices label="Premise source" options={[["generated", "Generate a premise"], ["given", "Use my premise"]]} value={topicMode} disabled={busy} onChange={editForm(setTopicMode)} />
      {topicMode === "given" ? <Field label="Story premise" multiline value={topic} maxLength={data?.settings?.max_topic_chars || 1200} editable={!busy} onChangeText={editForm(setTopic)} placeholder="A night-shift operator hears tomorrow’s emergency calls…" /> : <>
        <Field label="Story direction · optional" multiline value={direction} maxLength={1200} editable={!busy} onChangeText={editForm(setDirection)} placeholder="Leave empty for an original premise, or give it an angle" />
        <Button label="Suggest story premises" busy={busy} disabled={!data || !!data?.busy} onPress={suggest} />
        {ideas.map((idea, i) => <View key={i} style={{ gap: 8 }}><Text style={t.h2}>{idea.title}</Text><Text style={t.muted}>{idea.premise}</Text>{!!idea.reason && <Text style={t.faint}>{idea.reason}</Text>}<Button label={`Use premise ${i + 1}`} disabled={busy} onPress={() => { setSelectedIdeaProfile(ideaProfile); editForm(setGeneratedTopic)(idea.premise); }} /></View>)}
        {!!generatedTopic && <Field label="Selected generated premise" value={generatedTopic} multiline editable={!busy} onChangeText={editForm(setGeneratedTopic)} />}
        <Text style={t.faint}>Start with no premise to generate one automatically, or choose and refine a suggestion first.</Text>
      </>}
      <Choices label="Genre" options={(data?.genres || []).map(g => [g.id, g.label])} value={genre} disabled={busy} onChange={editForm(setGenre)} />
      <Choices label="Visual treatment" options={[["still", "Illustrated"], ["animated", "Animated"]]} value={format} disabled={busy} onChange={editForm(setFormat)} />
      {!!capabilities.visual_provider?.label && <Text style={t.faint}>{capabilities.visual_provider.label}</Text>}
      <Choices label="Length preset" options={[["60", "Short · 1 min"], ["300", "Episode · 5 min"], ["600", "Episode · 10 min"]]} value={duration} disabled={busy} onChange={editForm(setDuration)} />
      <Field label="Target duration · seconds" value={duration} editable={!busy} onChangeText={editForm(setDuration)} keyboardType="number-pad" inputStyle={{ maxWidth: 160 }} />
      {!!capabilities.voices?.length && <Choices label="Narrator" options={[["", "Default voice"], ...capabilities.voices.map(v => [v.id, v.label])]} value={voice} disabled={busy} onChange={editForm(setVoice)} />}
      <Button label={data?.settings?.auto_render ? "Create story & video" : "Create story draft"} kind="primary" busy={busy} disabled={!data || (topicMode === "given" && !topic.trim()) || !!data?.busy} onPress={create} />
      {!!data?.busy && <Text accessibilityLiveRegion="polite" style={t.faint}>PC production in progress · {data.job?.stage || "working"}. New productions wait until it finishes.</Text>}
      {capabilities.narrator_available === false && <Text style={t.faint}>Narration needs setup on the PC before a video can be rendered.</Text>}
      {(capabilities.reasons || []).map((reason, i) => <Text key={i} style={t.faint}>{text(reason)}</Text>)}
    </Card></Section>}
    {screen === "story-publishing" && <Publishing state={publishing} request={request} onError={setFailure} />}
    {screen === "story-library" && <Section title={`Production library${data?.projects ? ` · ${data.projects.length}` : ""}`} right={<Button small label="Refresh" busy={loading} onPress={load} />}>
      {!data?.projects?.length ? <Card><Empty icon="moon-outline" title="Your first story starts here" body="Choose a premise, genre and narrator. Manuscripts, scenes, final videos and publishing history stay together." /></Card> : data.projects.map(project => <Project key={project.id} project={project} request={request} host={host} token={token} publishing={publishing} onUnauthorized={onUnauthorized} onError={setFailure} onDirtyChange={projectDirty} workspaceActive={active} />)}
    </Section>}
    <Learning active={active} host={host} token={token} onUnauthorized={onUnauthorized} business="stories" onDirtyChange={memoryDirty} example={screen === "stories" && topicMode === "generated" && generatedTopic ? { title: "Selected story premise", text: generatedTopic, account_profile_id: selectedIdeaProfile } : data?.projects?.[0] ? { title: data.projects[0].title, text: data.projects[0].script || data.projects[0].topic, account_profile_id: data.projects[0].account_profile_id } : undefined} />
  </ScrollView>;
}
