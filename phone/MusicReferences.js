import React, { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Platform, Pressable, Text, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system";
import { Button, C, Field, Pill, t } from "./theme";
import BusinessMedia from "./BusinessMedia";
import { useWorkspace } from "./workspace";

const finished = status => ["completed", "failed", "cancelled", "needs_input"].includes(status);
const savedJobs = new Map();
const confirmReplace = proceed => {
  const message = "Replace the lyrics currently on this desk with the selected text file?";
  if (Platform.OS === "web") { if (globalThis.confirm(message)) proceed(); }
  else Alert.alert("Replace lyrics?", message, [{ text: "Keep my lyrics", style: "cancel" }, { text: "Replace lyrics", style: "destructive", onPress: proceed }]);
};

// Reference jobs update their own records; they never overwrite the creator's draft.
export default function MusicReferences({ host, token, onUnauthorized, active, enabled, busy: deskBusy, engineBusy, direction, onEdit, onLyrics, onBlocked }) {
  const { request } = useWorkspace({ host, token, onUnauthorized }, "/api/music");
  const [references, setReferences] = useState([]), [options, setOptions] = useState(null), [capabilities, setCapabilities] = useState(null);
  const scope = `${host}:${token}`;
  const [job, setJob] = useState(() => savedJobs.get(scope) || null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState(""), [preview, setPreview] = useState(false);
  const epoch = useRef(0), upload = useRef(null), controller = useRef(null), latest = useRef({ direction, onEdit, onLyrics });
  latest.current = { direction, onEdit, onLyrics };
  useEffect(() => { savedJobs.set(scope, job); if (savedJobs.size > 8) savedJobs.delete(savedJobs.keys().next().value); }, [scope, job]);
  const selected = references.find(row => row.id === direction.reference_id);
  const working = !!job && !finished(job.status);
  const blocked = busy || working || !!direction.reference_id && selected?.status !== "completed";
  useEffect(() => { onBlocked(blocked); }, [blocked, onBlocked]);
  useEffect(() => {
    ++epoch.current;
    return () => { ++epoch.current; controller.current?.abort(); upload.current?.cancelAsync().catch(() => {}); };
  }, [host, token]);
  useEffect(() => { if (!active) { ++epoch.current; controller.current?.abort(); upload.current?.cancelAsync().catch(() => {}); setBusy(false); setPreview(false); } }, [active]);
  useEffect(() => { setPreview(false); }, [direction.reference_id]);
  const refresh = useCallback(async version => {
    const rows = await request("/references");
    if (version === epoch.current) setReferences(rows.references || []);
  }, [request]);
  useEffect(() => {
    if (!active) return;
    const version = epoch.current;
    Promise.allSettled([request("/references/options"), request("/references"), request("/rap/capabilities")]).then(results => {
      if (version !== epoch.current) return;
      if (results[0].status === "fulfilled") setOptions(results[0].value);
      if (results[1].status === "fulfilled") setReferences(results[1].value.references || []);
      if (results[2].status === "fulfilled") setCapabilities(results[2].value);
      const failed = results.find(result => result.status === "rejected" && result.reason.name !== "AbortError");
      setError(failed?.reason.message || "");
    });
  }, [active, enabled, request]);
  useEffect(() => {
    if (!active || !options?.poll_ms || !references.some(row => !finished(row.status)) && !working) return;
    let alive = true, timer;
    const version = epoch.current;
    const tick = async () => {
      try {
        const [rows, nextJob] = await Promise.all([request("/references"), working ? request(`/rap/jobs/${encodeURIComponent(job.id)}`) : null]);
        if (!alive || version !== epoch.current) return;
        setReferences(rows.references || []);
        if (nextJob) {
          setJob(nextJob);
          if (finished(nextJob.status)) {
            await refresh(version);
            if (alive && version === epoch.current) setNotice(nextJob.status === "completed" ? "Description ready. Review it before adding its style hint." : nextJob.error || nextJob.message || "Listening did not complete.");
          }
        }
      } catch (e) { if (alive && version === epoch.current && e.name !== "AbortError") setError(e.message); }
      if (alive && version === epoch.current) timer = setTimeout(tick, options.poll_ms);
    };
    timer = setTimeout(tick, options.poll_ms);
    return () => { alive = false; clearTimeout(timer); };
  }, [active, options?.poll_ms, references, working, job?.id, request, refresh]);
  const run = async (operation, message) => {
    if (busy || deskBusy) return;
    const version = epoch.current;
    setBusy(true); setError(""); setNotice("");
    try { const result = await operation(version); if (version === epoch.current && result !== false && message) setNotice(message); }
    catch (e) { if (version === epoch.current && e.name !== "AbortError") setError(e.message || "This operation could not finish."); }
    finally { if (version === epoch.current) setBusy(false); }
  };
  const uploadReference = () => run(async version => {
    if (!enabled || !options) throw new Error("Start Resonance and refresh references before uploading.");
    const picked = await DocumentPicker.getDocumentAsync({ multiple: false, copyToCacheDirectory: true });
    if (version !== epoch.current || picked.canceled || !picked.assets?.[0]) return false;
    const file = picked.assets[0], extension = file.name.split(".").pop().toLowerCase();
    if (!options.extensions.map(value => value.replace(/^\./, "").toLowerCase()).includes(extension)) throw new Error("Choose a supported reference audio or video file.");
    if (file.size != null && (!file.size || file.size > options.max_upload_bytes)) throw new Error("This reference is empty or exceeds the displayed upload limit.");
    setNotice(`Uploading ${file.name} to your PC… Keep this desk open until it finishes.`);
    const headers = { Authorization: `Bearer ${token}`, "X-ClipBot": "1", "X-File-Name": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" };
    let response, result;
    if (Platform.OS === "web") {
      const body = file.file || await (await fetch(file.uri)).blob();
      if (!body.size || body.size > options.max_upload_bytes) throw new Error("This reference is empty or exceeds the displayed upload limit.");
      controller.current = new AbortController();
      response = await fetch(`${host}/api/music/references/upload`, { method: "POST", headers, body, signal: controller.current.signal });
      result = await response.json();
    } else {
      const info = await FileSystem.getInfoAsync(file.uri), size = file.size ?? info.size;
      if (!size || size > options.max_upload_bytes) throw new Error("This reference is empty or exceeds the displayed upload limit.");
      upload.current = FileSystem.createUploadTask(`${host}/api/music/references/upload`, file.uri, { httpMethod: "POST", uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT, headers });
      response = await upload.current.uploadAsync();
      if (!response) return false;
      result = JSON.parse(response.body || "{}");
    }
    if (version !== epoch.current) return;
    if (response.status === 401) onUnauthorized?.(true);
    if (response.status < 200 || response.status >= 300 || result.ok === false || !result.id) throw new Error(typeof result.detail === "string" ? result.detail : result.error || "The reference could not be saved.");
    setReferences(rows => [result, ...rows.filter(row => row.id !== result.id)]);
    latest.current.onEdit("reference_id", result.id);
  }, "Reference saved on your PC. Preview preparation is queued.");
  const importLyrics = () => run(async version => {
    if (!options) throw new Error("Refresh references to check the lyrics file limit first.");
    const picked = await DocumentPicker.getDocumentAsync({ multiple: false, copyToCacheDirectory: true });
    if (version !== epoch.current || picked.canceled || !picked.assets?.[0]) return false;
    const file = picked.assets[0];
    if (!/\.(txt|lrc)$/i.test(file.name)) throw new Error("Choose a UTF-8 .txt or .lrc lyrics file.");
    let text;
    if (Platform.OS === "web") {
      const body = file.file || await (await fetch(file.uri)).blob();
      if (!body.size || body.size > options.max_lyrics_file_bytes) throw new Error("The lyrics file is empty or too large.");
      text = await body.text();
    } else {
      const info = await FileSystem.getInfoAsync(file.uri), size = file.size ?? info.size;
      if (!size || size > options.max_lyrics_file_bytes) throw new Error("The lyrics file is empty or too large.");
      text = await FileSystem.readAsStringAsync(file.uri, { encoding: FileSystem.EncodingType.UTF8 });
    }
    if (version !== epoch.current) return;
    text = text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
    if (/\.lrc$/i.test(file.name)) text = text.split("\n").filter(line => !/^\s*\[(ar|ti|al|by|offset|length|re|ve):.*\]\s*$/i.test(line)).map(line => line.replace(/^\s*(?:\[\d{1,3}:\d{2}(?:[.:]\d+)?\])+\s*/, "")).join("\n");
    if (!text.trim() || text.includes("\u0000") || text.includes("\uFFFD") || text.length > 12000) throw new Error("Use a UTF-8 text file with at most 12,000 characters of lyrics.");
    const apply = () => { if (version === epoch.current) { latest.current.onLyrics(text); setNotice("Lyrics imported. Review them below before creating a take."); } };
    const draft = latest.current.direction;
    if (draft.lyrics?.trim() || draft.generated_lyrics?.trim()) confirmReplace(apply); else apply();
  }, "");
  const allBusy = busy || deskBusy;
  return <View style={{ gap: 12, borderTopWidth: 1, borderTopColor: C.line, paddingTop: 16 }}>
    <Text style={t.h2}>Reference track & lyrics</Text>
    <Text style={t.faint}>Add audio or video here, then tell Resonance which qualities to borrow. Your lyrics and musical direction stay editable.</Text>
    <Button label="Choose reference audio or video" disabled={allBusy || !enabled || !options} onPress={uploadReference} />
    {!!options && <Text style={t.faint}>{options.extensions.join(", ")} · up to {Math.floor(options.max_upload_bytes / 1048576)} MB</Text>}
    <Button label="Import .txt or .lrc lyrics" disabled={allBusy || !options} onPress={importLyrics} />
    <Button small label="Refresh references & listener" disabled={allBusy} onPress={() => run(async version => { const [limits, caps] = await Promise.all([request("/references/options"), request("/rap/capabilities"), refresh(version)]); if (version === epoch.current) { setOptions(limits); setCapabilities(caps); } }, "References refreshed.")} />
    {!!error && <Text accessibilityRole="alert" style={t.error}>{error}</Text>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={t.muted}>{notice}</Text>}
    <View style={{ gap: 8 }}>
      <Text style={t.label}>Reference for this take</Text>
      {[["", "No reference · written direction only"], ...references.map(row => [row.id, `${row.name || "Reference"} · ${row.status || "saved"}`])].map(([id, name]) => <Pressable key={id} accessibilityRole="radio" accessibilityState={{ selected: id === direction.reference_id, disabled: allBusy }} disabled={allBusy} onPress={() => onEdit("reference_id", id)} style={{ minHeight: 44, borderRadius: 6, borderWidth: 1, borderColor: id === direction.reference_id ? C.ember : C.line, backgroundColor: id === direction.reference_id ? C.emberSoft : C.s2, padding: 12 }}><Text style={t.muted}>{name}</Text></Pressable>)}
    </View>
    {!!direction.reference_id && !selected && <Text style={t.faint}>The selected reference is unavailable. Refresh or choose no reference before creating.</Text>}
    {!!selected && <>
      <Pill label={selected.status || "Saved"} />
      <Text accessibilityLiveRegion="polite" style={t.muted}>{[selected.phase, selected.message].filter(Boolean).join(" · ")}</Text>
      <Text style={t.faint}>{[selected.duration_seconds ? `${Number(selected.duration_seconds).toFixed(1)}s preview` : "Preview pending", Number(selected.tempo_bpm) > 0 ? `≈ ${Number(selected.tempo_bpm).toFixed(1)} BPM` : "Tempo not estimated"].join(" · ")}</Text>
      {!!selected.analysis_note && <Text selectable style={t.faint}>{selected.analysis_note}</Text>}
      {!!selected.audio_url && <Button label={preview ? "Close reference preview" : "Play reference preview"} onPress={() => setPreview(value => !value)} />}
      {preview && active && !!selected.audio_url && <BusinessMedia host={host} token={token} path={selected.audio_url} onUnauthorized={onUnauthorized} label={selected.name || "Reference preview"} />}
      <Button label="Retry preview analysis" disabled={allBusy || !enabled || !finished(selected.status) || working} onPress={() => run(async version => { const row = await request(`/references/${encodeURIComponent(selected.id)}/analyze`, { method: "POST", body: {} }); if (version === epoch.current) setReferences(rows => rows.map(item => item.id === row.id ? row : item)); }, "Preview analysis queued.")} />
      {!finished(selected.status) && <Button label="Cancel reference preparation" disabled={allBusy} onPress={() => run(async version => { await request(`/references/${encodeURIComponent(selected.id)}/cancel`, { method: "POST", body: {} }); await refresh(version); }, "Cancellation requested.")} />}
      <Button label="Listen & describe locally" disabled={allBusy || !enabled || engineBusy || working || selected.status !== "completed" || !capabilities?.describing} onPress={() => run(async version => { const next = await request("/references/describe", { method: "POST", body: { reference_id: selected.id } }); if (!next.id) throw new Error("The listener did not return a job. Refresh and try again."); if (version === epoch.current) setJob(next); }, "Local reference listening queued.")} />
      <Text style={t.faint}>{working ? [job.phase || job.status, job.message].filter(Boolean).join(" · ") : capabilities?.describing ? "The local audio model can describe the sound. Tempo analysis is a separate estimate." : "The local listening model is unavailable. Preview analysis and written notes still work."}</Text>
      {!!job?.error && <Text style={t.error}>{job.error}</Text>}
      {!!selected.caption && <Text selectable style={t.muted}>{selected.caption}</Text>}
      {!!selected.style_hint && <><Text selectable style={t.faint}>Style hint: {selected.style_hint}</Text><Button label="Append hint to musical direction" disabled={allBusy} onPress={() => { const style = [direction.style.trim(), selected.style_hint].filter(Boolean).join("\n"); if (style.length > 2000) { setError("Shorten your musical direction before adding this hint; the combined limit is 2,000 characters."); return; } onEdit("style", style); setNotice("Style hint appended. Your lyrics are unchanged."); }} /></>}
    </>}
    <Field label="What should this reference inspire? · optional" editable={!allBusy} value={direction.reference_notes || ""} multiline maxLength={options?.max_notes_chars} placeholder="The drum groove, warm bass, intimate delivery…" onChangeText={value => onEdit("reference_notes", value)} />
    {!enabled && <Text style={t.faint}>Start Resonance to upload, analyze or listen locally. Saved references remain available.</Text>}
  </View>;
}
