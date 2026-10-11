import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, Switch, Text, View } from "react-native";
import { Button, C, Card, Empty, Field, Pill, Section, t } from "./theme";
import Learning from "./Learning";
import BusinessMedia from "./BusinessMedia";
import MusicReferences from "./MusicReferences";
import { useWorkspace } from "./workspace";

const terminal = new Set(["completed", "failed", "cancelled", "needs_input"]);
const ongoing = job => job && !terminal.has(job.status);
const normalize = row => ({ ...row, ...row.parameters, id: row.id });
const savedWork = new Map();
const initialCreate = { title: "", style: "", lyrics: "", lyrics_mode: "generated", lyrics_direction: "", generated_lyrics: "", instrumental: false, mode: "general", duration_seconds: "60", seed: "-1", lm_seed: "-1", steps: "32", cot: "full", reference_id: "", reference_notes: "" };
const initialSession = { title: "", producer_brief: "", source: "", bpm: "120", bars: "8", seed: "0", beat_style: "trap", replace_backing: false };
const sessionFor = project => ({ ...initialSession, ...Object.fromEntries(["title", "producer_brief", "bpm", "bars", "seed", "beat_style"].map(key => [key, String(project[key] ?? initialSession[key])])), source: project.render_id ? `render:${project.render_id}` : project.song_id ? `song:${project.song_id}` : "", replace_backing: !!project.replace_backing });
export function Options({ label, options, value, onChange, disabled }) {
  return <View style={{ gap: 8 }}><Text style={t.label}>{label}</Text><View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>{options.map(([key, name]) => <Pressable key={key} accessibilityRole="radio" accessibilityLabel={name} accessibilityState={{ selected: key === value, disabled: !!disabled }} aria-checked={key === value} disabled={disabled} onPress={() => onChange(key)} style={({ pressed }) => ({ minHeight: 44, paddingHorizontal: 12, justifyContent: "center", borderRadius: 6, borderWidth: 1, borderColor: key === value ? C.ember : C.line, backgroundColor: key === value ? C.emberSoft : C.s2, opacity: pressed ? 0.7 : 1 })}><Text style={t.muted}>{name}</Text></Pressable>)}</View></View>;
}
export default function Music({ host, token, onUnauthorized, onDirtyChange, screen, active, runtime }) {
  const sessionKey = `${host}:${token}`, restored = savedWork.get(sessionKey) || {};
  const api = useWorkspace({ host, token, onUnauthorized }, "/api/music");
  const { request, action, error, setError, busy, notice } = api;
  const [engine, setEngine] = useState(null), [reaper, setReaper] = useState(null), [songs, setSongs] = useState([]), [renders, setRenders] = useState([]);
  const [direction, setDirection] = useState({ ...initialCreate, ...restored.direction }), [session, setSession] = useState(() => restored.session || (restored.project ? { ...sessionFor(restored.project), producer_brief: restored.producer?.brief || restored.project.producer_brief || "" } : initialSession)), [dirty, setDirty] = useState(restored.dirty || { create: false, session: false });
  const [referenceBlocked, setReferenceBlocked] = useState(!!restored.direction?.reference_id);
  const [learningDirty, setLearningDirty] = useState(false), [lyricsProfile, setLyricsProfile] = useState("");
  const [generation, setGeneration] = useState(restored.generation || null), [producer, setProducer] = useState(restored.producer || null), [project, setProject] = useState(restored.project || null), [selected, setSelected] = useState(null), [preview, setPreview] = useState(null);
  useEffect(() => { savedWork.set(sessionKey, { generation, producer, project, direction, session, dirty }); if (savedWork.size > 8) savedWork.delete(savedWork.keys().next().value); }, [sessionKey, generation, producer, project, direction, session, dirty]);
  const edit = (setter, key, value) => { setter(d => ({ ...d, [key]: value })); setDirty(d => ({ ...d, [setter === setDirection ? "create" : "session"]: true })); };
  useEffect(() => { onDirtyChange?.({ dirty: dirty.create || dirty.session || learningDirty, persistent: true }); }, [dirty, learningDirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const load = useCallback(async () => {
    const results = await Promise.allSettled([request("/status"), request("/songs"), request("/reaper/status"), request("/renders")]);
    if (results[0].status === "fulfilled") setEngine(results[0].value);
    if (results[1].status === "fulfilled") setSongs(results[1].value.songs || []);
    if (results[2].status === "fulfilled") setReaper(results[2].value);
    if (results[3].status === "fulfilled") setRenders(results[3].value.renders || []);
    const failed = results.find(r => r.status === "rejected" && r.reason?.name !== "AbortError");
    setError(failed?.reason.message || "");
  }, [request, setError]);
  useEffect(() => { if (active) load(); }, [active, runtime?.enabled, runtime?.busy, load]);
  useEffect(() => {
    if (!active) return;
    const jobs = ongoing(generation) || ongoing(producer) || project?.busy || project?.revisions?.some(r => !terminal.has(r.status));
    if (!jobs) return;
    let alive = true, timer;
    const tick = async () => {
      try {
        const [nextGeneration, nextProducer, nextProject] = await Promise.all([
          ongoing(generation) ? request(`/jobs/${generation.id}`) : null,
          ongoing(producer) ? request(`/production-jobs/${producer.id}`) : null,
          project?.id ? request(`/reaper/projects/${project.id}`) : null,
        ]);
        if (!alive) return;
        if (nextGeneration) setGeneration(nextGeneration);
        if (nextProducer) setProducer(nextProducer);
        if (nextProject) setProject(normalize(nextProject.project || nextProject));
        if (nextGeneration && terminal.has(nextGeneration.status)) await load();
      } catch (e) { if (alive && e.name !== "AbortError") setError(e.message); }
      if (alive) timer = setTimeout(tick, 3000);
    };
    timer = setTimeout(tick, 1500); return () => { alive = false; clearTimeout(timer); };
  }, [active, generation, producer, project, request, load, setError]);
  useEffect(() => { if (!active) setPreview(null); }, [active]);
  const enabled = !!runtime?.enabled;
  const create = () => action(async () => {
    const duration = Number(direction.duration_seconds), steps = Number(direction.steps);
    if (!Number.isInteger(duration) || duration < 10 || duration > 360 || !Number.isInteger(steps) || steps < 8 || steps > 64) throw new Error("Enter a length from 10 to 360 seconds and 8 to 64 generation steps.");
    const { generated_lyrics, instrumental, ...fields } = direction;
    setGeneration(await request("/create", { method: "POST", body: { ...fields, lyrics_mode: direction.instrumental ? "given" : direction.lyrics_mode, lyrics: direction.instrumental ? "" : direction.lyrics_mode === "given" ? direction.lyrics : direction.generated_lyrics, duration_seconds: duration, steps, seed: Number(direction.seed), lm_seed: Number(direction.lm_seed) } })); setDirty(d => ({ ...d, create: false }));
  }, "Local generation started. Your take will appear in Library.");
  const prepare = async () => {
    const bpm = Number(session.bpm), bars = Number(session.bars), seed = Number(session.seed);
    if (![bpm, bars, seed].every(Number.isInteger) || bpm < 40 || bpm > 240 || bars < 1 || bars > 128 || seed < 0) throw new Error("Use 40–240 BPM, 1–128 bars and a nonnegative beat seed.");
    const { source, ...fields } = session, body = { ...fields, bpm, bars, seed };
    if (source.startsWith("song:")) body.song_id = source.slice(5);
    if (source.startsWith("render:")) body.render_id = source.slice(7);
    const result = await request("/reaper/projects", { method: "POST", body });
    const next = normalize(result.project || result); setProject(next); setDirty(d => ({ ...d, session: false })); await load(); return next;
  };
  const produce = () => action(async () => {
    if (!session.producer_brief.trim()) throw new Error("Add production notes describing what should change.");
    const matches = project && ["title", "bpm", "bars", "seed", "beat_style", "replace_backing", "source"].every(key => String(sessionFor(project)[key]) === String(session[key]));
    const target = matches ? project : await prepare();
    setProducer(await request("/produce", { method: "POST", body: { project_id: target.id, brief: session.producer_brief, auto_apply: true } })); setDirty(d => ({ ...d, session: false }));
  }, "Producer started from your notes. Listen to the resulting revision before using it.");
  const loadProject = async row => {
    const result = await request(`/reaper/projects/${row.id}`), next = normalize(result.project || result);
    setProject(next); return next;
  };
  const selectProject = row => action(async () => {
    const next = await loadProject(row);
    setSession(sessionFor(next)); setDirty(d => ({ ...d, session: false }));
  }, "Session loaded.");
  const source = [...songs.map(s => ({ ...s, kind: "song" })), ...renders.map(r => ({ ...r, kind: "render" }))].find(row => `${row.kind}:${row.id}` === session.source);
  const dry = source?.dry_vocal_available || source?.has_dry_vocal || source?.stems?.dry_vocal || source?.dry_vocal;
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 16, paddingBottom: 36 }}>
    <Section title="Resonance"><Text style={t.muted}>Local music creation and editable REAPER sessions on your PC.</Text><Button small label="Check local tools" busy={busy} onPress={() => action(load, "Local tools checked.")} style={{ marginTop: 12 }} /></Section>
    {!!error && <Card style={{ marginBottom: 16 }}><Text accessibilityRole="alert" style={t.error}>{error}</Text></Card>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={[t.muted, { marginBottom: 16 }]}>{notice}</Text>}
    {screen === "music" && <Section title="Create a take"><Card style={{ gap: 16 }}>
      <Text style={t.faint}>{engine?.message || "Checking local engine…"}</Text>
      {[['title', 'Take title'], ['style', 'Musical direction · optional']].map(([key, label]) => <Field editable={!busy} key={key} label={label} value={direction[key]} multiline={key !== "title"} maxLength={key === "title" ? 120 : 2000} onChangeText={value => edit(setDirection, key, value)} />)}
      <MusicReferences key={sessionKey} host={host} token={token} onUnauthorized={onUnauthorized} active={active && screen === "music"} enabled={enabled} busy={busy} engineBusy={engine?.busy || ongoing(generation) || ongoing(producer)} direction={direction} onEdit={(key, value) => edit(setDirection, key, value)} onLyrics={lyrics => { setDirection(d => ({ ...d, lyrics, lyrics_mode: "given", instrumental: false })); setDirty(d => ({ ...d, create: true })); }} onBlocked={setReferenceBlocked} />
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}><Text style={[t.muted, { flex: 1 }]}>Instrumental</Text><Switch disabled={busy} accessibilityLabel="Instrumental" value={direction.instrumental} onValueChange={v => edit(setDirection, "instrumental", v)} /></View>
      {!direction.instrumental && <><Options disabled={busy} label="Lyrics source" options={[["generated", "Generate lyrics"], ["given", "Use my lyrics"]]} value={direction.lyrics_mode} onChange={v => edit(setDirection, "lyrics_mode", v)} />
      {direction.lyrics_mode === "given" ? <Field editable={!busy} label="Your lyrics" value={direction.lyrics} multiline maxLength={12000} onChangeText={v => edit(setDirection, "lyrics", v)} /> : <><Field editable={!busy} label="Lyrics direction · optional" value={direction.lyrics_direction} multiline maxLength={4000} onChangeText={v => edit(setDirection, "lyrics_direction", v)} /><Button label="Suggest lyrics" busy={busy} disabled={!enabled || referenceBlocked} onPress={() => action(async () => { const result = await request("/lyrics", { method: "POST", timeout: 300000, body: { style: direction.style, direction: direction.lyrics_direction, duration_seconds: Number(direction.duration_seconds), mode: direction.mode, reference_id: direction.reference_id, reference_notes: direction.reference_notes } }); setLyricsProfile(result.account_profile_id || ""); edit(setDirection, "generated_lyrics", result.lyrics || ""); if (!direction.title && result.title) setDirection(d => ({ ...d, title: result.title })); }, "Lyrics suggested. Edit them or generate a take.")} />{!!direction.generated_lyrics && <Field editable={!busy} label="Generated lyrics" value={direction.generated_lyrics} multiline maxLength={12000} onChangeText={v => edit(setDirection, "generated_lyrics", v)} />}<Text style={t.faint}>Leave the direction empty to let Resonance choose. Lyrics are generated when you start the take.</Text></> }</>}
      <Options disabled={busy} label="Performance" options={[["general", "General music"], ["rap", "Rap"]]} value={direction.mode} onChange={v => edit(setDirection, "mode", v)} />
      {[["duration_seconds", "Length in seconds"], ["seed", "Audio seed"], ["lm_seed", "Composition seed"], ["steps", "Generation steps"]].map(([key, label]) => <Field editable={!busy} key={key} label={label} value={direction[key]} keyboardType="numbers-and-punctuation" onChangeText={v => edit(setDirection, key, v)} />)}
      <Text style={t.faint}>Seed −1 chooses a new take.</Text>
      <Options disabled={busy} label="Composition planning" options={[["full", "Full composition"], ["melody", "Melody"], ["off", "Off"]]} value={direction.cot} onChange={v => edit(setDirection, "cot", v)} />
      <Button label="Generate local take" kind="primary" busy={busy} disabled={!enabled || !engine?.ready || engine?.busy || ongoing(generation) || referenceBlocked} onPress={create} />
      {referenceBlocked && <Text style={t.faint}>Wait for reference preparation or listening to finish, or choose no reference.</Text>}
      {!enabled && <Text style={t.faint}>Start Resonance above to generate a take.</Text>}
      {!!generation && <Job job={generation} onCancel={() => action(async () => setGeneration(await request(`/jobs/${generation.id}/cancel`, { method: "POST", body: {} })), "Cancellation requested.")} busy={busy} />}
    </Card></Section>}
    {screen === "music-library" && <>
      <Section title="Saved takes">{!songs.length && !renders.length && <Card><Empty icon="musical-notes-outline" title="No takes yet" body="Create a local take, then return here to listen before producing it." /></Card>}
        {[...songs.map(s => ({ ...s, kind: "song" })), ...renders.map(r => ({ ...r, kind: "render" }))].map(row => <Card key={`${row.kind}:${row.id}`} style={{ gap: 10, marginBottom: 12 }}><Text style={t.h2}>{row.title || "Artist version"}</Text><Text style={t.faint}>{row.style || row.voice_name || "Local source"}</Text><Button label={`Audition ${row.title || "artist version"}`} disabled={busy} onPress={() => action(async () => { const result = row.kind === "song" ? await request(`/songs/${row.id}`) : row; setSelected({ ...result, kind: row.kind }); setPreview(result.audio_url ? { path: result.audio_url, label: result.title || "Source audition" } : null); }, "Source loaded for audition.")} /></Card>)}
      </Section>
      {!!selected && <Card style={{ gap: 14 }}><Text style={t.h2}>{selected.title}</Text><Text selectable style={t.muted}>{selected.lyrics || "No lyrics saved."}</Text>{!preview && <Text style={t.faint}>No playable audio is registered for this take.</Text>}<Button label="Use this source for a session" onPress={() => { edit(setSession, "source", `${selected.kind}:${selected.id}`); setSession(s => ({ ...s, title: selected.title || s.title })); }} /></Card>}
    </>}
    {screen === "music-production" && <>
      <Section title="Prepare an editable session"><Card style={{ gap: 16 }}>
        <Text style={t.faint}>{reaper?.message || "Checking local REAPER setup…"}</Text>
        <Text style={t.faint}>Beat controls prepare a new session. Production notes direct changes to the selected session.</Text>
        <Options disabled={busy} label="Source take" options={[["", "Original beat"], ...songs.map(s => [`song:${s.id}`, s.title || s.id]), ...renders.map(r => [`render:${r.id}`, r.title || "Artist version"])]} value={session.source} onChange={v => { edit(setSession, "source", v); setSession(s => ({ ...s, replace_backing: false })); }} />
        <Field editable={!busy} label="Session title" value={session.title} onChangeText={v => edit(setSession, "title", v)} />
        <Field editable={!busy} label="Production notes" value={session.producer_brief} multiline maxLength={2000} onChangeText={v => edit(setSession, "producer_brief", v)} />
        <Options disabled={busy} label="Starting beat" options={[["trap", "Trap"], ["boom-bap", "Boom bap"], ["four-on-floor", "Four on the floor"]]} value={session.beat_style} onChange={v => edit(setSession, "beat_style", v)} />
        {[["bpm", "Tempo · BPM"], ["bars", "Beat length · bars"], ["seed", "Beat seed"]].map(([key, label]) => <Field editable={!busy} key={key} label={label} value={session[key]} keyboardType="number-pad" onChangeText={v => edit(setSession, key, v)} />)}
        <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}><Text style={[t.muted, { flex: 1 }]}>Replace backing using saved dry vocal</Text><Switch accessibilityLabel="Replace backing using saved dry vocal" value={session.replace_backing} disabled={!dry || busy} onValueChange={v => edit(setSession, "replace_backing", v)} /></View>
        {!dry && <Text style={t.faint}>Replacing backing needs a source with a saved dry vocal.</Text>}
        <Button label="Prepare new session" disabled={!enabled || !reaper?.ready || reaper?.busy || busy} onPress={() => action(prepare, "Editable session saved on your PC.")} />
        <Button label="Produce from these notes" kind="primary" busy={busy} disabled={!enabled || !reaper?.ready || reaper?.busy || ongoing(producer)} onPress={produce} />
        {!enabled && <Text style={t.faint}>Start Resonance above to prepare or produce.</Text>}
        {!!producer && <Job job={producer} onCancel={() => action(async () => setProducer(await request(`/production-jobs/${producer.id}/cancel`, { method: "POST", body: {} })), "Cancellation requested.")} busy={busy} />}
        {!!producer?.plan && <Text selectable style={t.faint}>{JSON.stringify({ plan: producer.plan, review: producer.review }, null, 2)}</Text>}
        {producer?.status === "needs_input" && !!producer.plan && <Button label="Apply reviewed plan" disabled={!enabled || busy || !project} onPress={() => action(async () => { await request(`/reaper/projects/${project.id}/edit`, { method: "POST", body: { plan: producer.plan, render: true } }); await loadProject(project); }, "Reviewed plan sent to REAPER.")} />}
      </Card></Section>
      <Section title="Saved REAPER sessions">{(reaper?.projects || []).map(row => <Button key={row.id} label={row.title || row.id} disabled={busy || dirty.session} onPress={() => selectProject(row)} style={{ marginBottom: 10 }} />)}{!(reaper?.projects || []).length && <Text style={t.muted}>Prepare a session to keep editable production work here.</Text>}{dirty.session && <Text style={t.faint}>Use or discard your current notes before loading another session.</Text>}</Section>
      {!!project && <Section title={project.title || "Selected session"}><Card style={{ gap: 14 }}><Text style={t.faint}>{project.producer_brief || "Session saved on your PC."}</Text>
        <Button label="Open REAPER on PC" disabled={busy} onPress={() => action(async () => { const result = await request(`/reaper/projects/${project.id}/open`, { method: "POST", body: {} }); if (result.opened === false) throw new Error(result.message || "REAPER could not open on your PC."); }, "REAPER opened on your PC.")} />
        <Button label="Export current session" disabled={!enabled || busy || reaper?.busy || project.busy} onPress={() => action(async () => { await request(`/reaper/projects/${project.id}/export`, { method: "POST", body: {} }); await loadProject(project); }, "Export queued on your PC.")} />
        {project.busy && <Button label="Cancel session export" disabled={busy} onPress={() => action(async () => { await request(`/reaper/projects/${project.id}/cancel`, { method: "POST", body: {} }); await loadProject(project); }, "Session cancellation requested.")} />}
        {(project.revisions || []).map((row, i) => <View key={row.id || i} style={{ gap: 8, borderTopWidth: 1, borderTopColor: C.line, paddingTop: 14 }}><Text style={t.h2}>{row.title || row.label || `Version ${i + 1}`}</Text><Text style={t.faint}>{row.message || row.status}</Text>{!!row.audio_url && <Button label={`Audition version ${i + 1}`} onPress={() => setPreview({ path: row.audio_url, label: `Version ${i + 1}` })} />}</View>)}
        {!project.revisions?.length && <Text style={t.faint}>Export a version to audition it here.</Text>}
      </Card></Section>}
    </>}
    {!!preview && ["music-library", "music-production"].includes(screen) && <Card style={{ gap: 14, marginTop: 16 }}><BusinessMedia host={host} token={token} path={preview.path} label={preview.label} onUnauthorized={onUnauthorized} /><Button label="Close audio preview" onPress={() => setPreview(null)} /></Card>}
    <Learning active={active} host={host} token={token} onUnauthorized={onUnauthorized} business="music" onDirtyChange={setLearningDirty} example={screen === "music" && !direction.instrumental && direction.lyrics_mode === "generated" && direction.generated_lyrics ? { title: direction.title, text: direction.generated_lyrics, account_profile_id: lyricsProfile } : selected ? { title: selected.title, text: selected.lyrics || selected.style, account_profile_id: selected.account_profile_id } : undefined} />
    {(dirty.create || dirty.session) && <Button label="Discard unsaved music direction" onPress={() => { setDirection(initialCreate); setSession(initialSession); setDirty({ create: false, session: false }); }} style={{ marginTop: 16 }} />}
  </ScrollView>;
}
function Job({ job, onCancel, busy }) {
  return <View style={{ gap: 10 }}><Pill label={job.status || "Queued"} /><Text accessibilityLiveRegion="polite" style={t.muted}>{job.phase || job.message || job.status}</Text>{!!(job.error || job.review?.summary) && <Text selectable style={job.error ? t.error : t.faint}>{job.error || job.review.summary}</Text>}{ongoing(job) && <Button label="Cancel current music job" disabled={busy} onPress={onCancel} />}</View>;
}
