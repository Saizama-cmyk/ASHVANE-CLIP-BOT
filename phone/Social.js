import React, { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Linking, Platform, ScrollView, Switch, Text, View } from "react-native";
import { Button, Card, Empty, Field, Section, t } from "./theme";
import BusinessMedia from "./BusinessMedia";
import { Options } from "./Music";
import { useWorkspace } from "./workspace";

const platforms = ["instagram", "tiktok", "youtube", "discord", "facebook", "x", "linkedin"];
const freshClient = () => ({ name: "", description: "", platforms: [], rules: "", style_notes: { A: "", B: "", C: "" }, fresh_footage_required: true });
const freshPost = (client) => ({ title: "", script: "", caption: "", hashtags: [], pinned_comment: "", platforms: client?.platforms || [], style: "", status: "draft", scheduled_at: "", notes: "", asset_ids: [], requires_fresh_footage: !!client?.fresh_footage_required });
const confirm = (title, message, proceed) => {
  if (Platform.OS === "web") { if (globalThis.confirm(message)) proceed(); }
  else Alert.alert(title, message, [{ text: "Keep editing", style: "cancel" }, { text: "Continue", style: "destructive", onPress: proceed }]);
};
export default function Social({ host, token, onUnauthorized, onDirtyChange, screen, active, runtime }) {
  const { request, action, error, setError, busy, notice } = useWorkspace({ host, token, onUnauthorized }, "/api/social");
  const [clients, setClients] = useState([]), [client, setClient] = useState(null), [clientDraft, setClientDraft] = useState(freshClient);
  const [items, setItems] = useState([]), [assets, setAssets] = useState([]), [calendar, setCalendar] = useState([]), [links, setLinks] = useState({});
  const [post, setPost] = useState(null), [hashtagsText, setHashtagsText] = useState(""), [brief, setBrief] = useState(""), [style, setStyle] = useState("A"), [draftPlatforms, setDraftPlatforms] = useState([]), [preview, setPreview] = useState(null);
  const [dirty, setDirty] = useState({ client: false, post: false, brief: false, links: false });
  const epoch = useRef(0), selectedId = useRef(null);
  const hasEdits = Object.values(dirty).some(Boolean);
  useEffect(() => { onDirtyChange?.(hasEdits); }, [hasEdits, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const mark = (key, value = true) => setDirty(d => ({ ...d, [key]: value }));
  const editClient = (key, value) => { setClientDraft(d => ({ ...d, [key]: value })); mark("client"); };
  const editPost = (key, value) => { setPost(p => ({ ...p, [key]: value })); mark("post"); };
  const select = useCallback(async row => {
    const version = ++epoch.current; selectedId.current = row.id;
    const results = await Promise.all([request(`/clients/${row.id}/content`), request(`/clients/${row.id}/assets`), request(`/clients/${row.id}/accounts`)]);
    if (version !== epoch.current) return;
    setClient(row); setClientDraft({ ...freshClient(), ...row }); setItems(results[0].items || []); setAssets(results[1].assets || []); setLinks(results[2].public_handles || {});
    setPost(null); setBrief(""); setDraftPlatforms(row.platforms || []); setStyle(Object.keys(row.style_notes || {})[0] || "A"); setPreview(null); setDirty({ client: false, post: false, brief: false, links: false });
  }, [request]);
  const load = useCallback(async () => {
    const data = await request("/clients"); if (data.error) throw new Error(data.error);
    setClients(data.clients || []);
    if (!selectedId.current && data.clients?.length) await select(data.clients[0]);
  }, [request, select]);
  useEffect(() => { if (active) load().catch(e => { if (e.name !== "AbortError") setError(e.message); }); }, [active, load, setError]);
  useEffect(() => { if (active && screen === "social-calendar") request("/calendar").then(data => setCalendar(data.items || [])).catch(e => { if (e.name !== "AbortError") setError(e.message); }); }, [active, screen, request, setError]);
  const changeClient = row => {
    const go = () => action(() => select(row), "Client desk loaded.");
    if (hasEdits) confirm("Change client?", "Discard the unsaved client, post, brief or profile edits and load another client?", go); else go();
  };
  const openPost = row => {
    const go = () => { setPost({ ...freshPost(client), ...row }); setHashtagsText((row.hashtags || []).join(", ")); mark("post", false); };
    if (dirty.post) confirm("Load another post?", "Discard your unsaved post edits?", go); else go();
  };
  const saveClient = () => action(async () => {
    if (!clientDraft.name.trim()) throw new Error("Enter a client name.");
    const body = Object.fromEntries(["name", "description", "platforms", "rules", "style_notes", "fresh_footage_required"].map(key => [key, clientDraft[key]]));
    const result = await request(client ? `/clients/${client.id}` : "/clients", { method: client ? "PATCH" : "POST", body });
    const saved = result.client; setClient(saved); selectedId.current = saved.id; setClientDraft({ ...freshClient(), ...saved }); mark("client", false); await load();
  }, "Client direction saved.");
  const savePost = () => action(async () => {
    if (!post?.title.trim()) throw new Error("Enter a working title.");
    let date = "";
    if (post.scheduled_at) { const parsed = new Date(post.scheduled_at); if (Number.isNaN(parsed.valueOf())) throw new Error("Enter a calendar time including timezone, such as 2026-10-20T15:00:00-05:00."); date = parsed.toISOString(); }
    if (post.status === "scheduled" && !date) throw new Error("Add a calendar time for a scheduled planning record.");
    const keys = ["title", "script", "caption", "hashtags", "pinned_comment", "platforms", "style", "status", "notes", "asset_ids", "requires_fresh_footage"];
    const body = { ...Object.fromEntries(keys.map(k => [k, post[k]])), scheduled_at: date, hashtags: hashtagsText.split(",").map(s => s.trim()).filter(Boolean) };
    const result = await request(post.id ? `/content/${post.id}` : `/clients/${client.id}/content`, { method: post.id ? "PATCH" : "POST", body });
    setPost(result.item); setHashtagsText((result.item.hashtags || []).join(", ")); setItems(rows => [result.item, ...rows.filter(p => p.id !== result.item.id)]); mark("post", false);
  }, "Post saved for manual publishing.");
  const draft = () => action(async () => {
    if (dirty.post) throw new Error("Save your post edits before drafting another post.");
    if (!brief.trim()) throw new Error("Describe the post you want to draft.");
    const result = await request(`/clients/${client.id}/draft`, { method: "POST", timeout: 300000, body: { brief, style, platforms: draftPlatforms } });
    setPost(result.item); setHashtagsText((result.item.hashtags || []).join(", ")); setItems(rows => [result.item, ...rows.filter(p => p.id !== result.item.id)]); mark("brief", false); mark("post", false);
  }, "Local draft saved. Review its claims and footage requirements.");
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 16, paddingBottom: 36 }}>
    <Section title="Social Studio"><Text style={t.muted}>Client direction, original drafts and a manual publishing calendar.</Text><Button small label="Reload client list" busy={busy} onPress={() => action(load, "Client list refreshed.")} style={{ marginTop: 12 }} /></Section>
    {!!error && <Card style={{ marginBottom: 16 }}><Text accessibilityRole="alert" style={t.error}>{error}</Text></Card>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={[t.muted, { marginBottom: 16 }]}>{notice}</Text>}
    {!!clients.length && <Section title="Active client"><Options label="Client" options={clients.map(c => [c.id, c.name])} value={client?.id} disabled={busy} onChange={id => changeClient(clients.find(c => c.id === id))} /></Section>}
    {screen === "social" && <Section title={client ? "Client direction" : "New client"}><Card style={{ gap: 16 }}>
      <Field editable={!busy} label="Client name" value={clientDraft.name} maxLength={120} onChangeText={v => editClient("name", v)} />
      <Field editable={!busy} label="About this client" value={clientDraft.description} multiline onChangeText={v => editClient("description", v)} />
      <Platforms disabled={busy} label="Client platforms" selected={clientDraft.platforms} onChange={v => editClient("platforms", v)} />
      <Field editable={!busy} label="Content rules" value={clientDraft.rules} multiline maxLength={6000} onChangeText={v => editClient("rules", v)} />
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}><Text style={[t.muted, { flex: 1 }]}>New content requires fresh footage</Text><Switch disabled={busy} accessibilityLabel="New content requires fresh footage" value={clientDraft.fresh_footage_required} onValueChange={v => editClient("fresh_footage_required", v)} /></View>
      {Object.entries({ A: "", B: "", C: "", ...clientDraft.style_notes }).map(([key, value]) => <Field editable={!busy} key={key} label={`Style ${key} direction`} value={value} multiline onChangeText={v => editClient("style_notes", { ...clientDraft.style_notes, [key]: v })} />)}
      <Button label="Save client direction" kind="primary" busy={busy} onPress={saveClient} />
      <Button label="New client" disabled={busy} onPress={() => { const go = () => { ++epoch.current; selectedId.current = "new"; setClient(null); setClientDraft(freshClient()); setItems([]); setAssets([]); setLinks({}); setPost(null); setBrief(""); setDirty({ client: false, post: false, brief: false, links: false }); }; if (hasEdits) confirm("New client?", "Discard your unsaved client edits and start a new profile?", go); else go(); }} />
    </Card></Section>}
    {!client && screen !== "social" && <Card><Empty icon="people-outline" title="Choose a client first" body="Open Clients to select an existing client or save a new profile." /></Card>}
    {client && screen === "social-content" && <>
      <Section title="Draft from a brief"><Card style={{ gap: 16 }}><Field editable={!busy} label="What should this post do?" value={brief} multiline maxLength={4000} onChangeText={v => { setBrief(v); mark("brief"); }} />
        <Options disabled={busy} label="Client style" options={Object.keys(client.style_notes || { A: "", B: "", C: "" }).map(key => [key, `Style ${key}`])} value={style} onChange={v => { setStyle(v); mark("brief"); }} />
        <Text selectable style={t.faint}>{client.style_notes?.[style] || "No style guidance saved."}</Text>
        <Platforms disabled={busy} label="Draft platforms" selected={draftPlatforms} onChange={v => { setDraftPlatforms(v); mark("brief"); }} />
        <Button label="Draft with local AI" kind="primary" busy={busy} disabled={!runtime?.enabled} onPress={draft} />
        {!runtime?.enabled && <Text style={t.faint}>Start Social Studio above to use local AI drafting. Saved posts remain editable.</Text>}
      </Card></Section>
      <Section title="Saved client posts"><Button label="Write a new post" disabled={busy} onPress={() => openPost(freshPost(client))} style={{ marginBottom: 14 }} />{items.map(row => <Button key={row.id} label={`${row.title} · ${row.status}`} disabled={busy} onPress={() => openPost(row)} style={{ marginBottom: 10 }} />)}{!items.length && <Text style={t.muted}>No saved posts for this client. Draft from a brief or write your own.</Text>}</Section>
      {!!post && <Section title="Post editor"><Card style={{ gap: 16 }}>
        {[["title", "Working title"], ["script", "Script"], ["caption", "Caption"], ["pinned_comment", "Pinned comment"], ["notes", "Private production notes"]].map(([key, label]) => <Field editable={!busy} key={key} label={label} value={post[key] || ""} multiline={key !== "title"} maxLength={6000} onChangeText={v => editPost(key, v)} />)}
        <Field editable={!busy} label="Hashtags · comma separated" value={hashtagsText} onChangeText={v => { setHashtagsText(v); mark("post"); }} />
        <Platforms disabled={busy} label="Post platforms" selected={post.platforms} onChange={v => editPost("platforms", v)} />
        <Options disabled={busy} label="Editorial status" options={["draft", "review", "ready", "scheduled", "posted"].map(k => [k, k[0].toUpperCase() + k.slice(1)])} value={post.status} onChange={v => editPost("status", v)} />
        <Field editable={!busy} label="Calendar time · include timezone" value={post.scheduled_at || ""} placeholder="2026-10-20T15:00:00-05:00" autoCapitalize="none" onChangeText={v => editPost("scheduled_at", v)} />
        <Text style={t.faint}>Calendar entries plan manual publishing. They do not send posts to an account.</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}><Text style={[t.muted, { flex: 1 }]}>Fresh footage required</Text><Switch disabled={busy} accessibilityLabel="Fresh footage required" value={!!post.requires_fresh_footage} onValueChange={v => editPost("requires_fresh_footage", v)} /></View>
        {!!assets.length && <View style={{ gap: 8 }}><Text style={t.label}>Reference assets</Text>{assets.map(a => <View key={a.id} style={{ flexDirection: "row", gap: 12, alignItems: "center" }}><Text style={[t.muted, { flex: 1 }]}>{a.name}{a.historical ? " · historical" : ""}</Text><Switch disabled={busy} accessibilityLabel={`Attach ${a.name}`} value={(post.asset_ids || []).includes(a.id)} onValueChange={on => editPost("asset_ids", on ? [...(post.asset_ids || []), a.id] : post.asset_ids.filter(k => k !== a.id))} /></View>)}</View>}
        {!!post.asset_ids?.length && <Text style={t.faint}>{post.asset_ids.length} reference assets selected</Text>}
        <Button label="Save post" kind="primary" busy={busy} onPress={savePost} />
        {!!post.id && <Button label="Delete saved draft" disabled={busy} onPress={() => confirm("Delete post?", "Delete this local saved post? Published content stays online.", () => action(async () => { await request(`/content/${post.id}`, { method: "DELETE" }); setItems(rows => rows.filter(p => p.id !== post.id)); setPost(null); mark("post", false); }, "Saved post deleted."))} />}
      </Card></Section>}
    </>}
    {client && screen === "social-calendar" && <Section title={`${client.name} calendar`}><Text style={[t.faint, { marginBottom: 14 }]}>Planning records for manual publishing.</Text>{calendar.filter(row => row.client_id === client.id).map(row => <Card key={row.id} style={{ gap: 8, marginBottom: 12 }}><Text style={t.h2}>{row.title}</Text><Text style={t.body}>{new Date(row.scheduled_at).toLocaleString()}</Text><Text style={t.faint}>{row.status} · {(row.platforms || []).join(", ")}</Text></Card>)}{!calendar.some(row => row.client_id === client.id) && <Card><Empty icon="calendar-outline" title="No dates planned" body="Add a calendar time in the post editor to plan a release." /></Card>}</Section>}
    {client && screen === "social-assets" && <Section title={`${client.name} assets`}><Text style={[t.faint, { marginBottom: 14 }]}>Archive assets are historical references. Add fresh recordings to the managed client folder on your PC.</Text>{assets.map(row => <Card key={row.id} style={{ gap: 12, marginBottom: 12 }}><Text style={t.h2}>{row.name}</Text><Text style={t.faint}>{row.kind}{row.historical ? " · Historical archive" : ""}</Text>{["audio", "video", "image"].includes(row.kind) ? <Button label={`Preview ${row.name}`} onPress={() => setPreview(row)} /> : <Text style={t.faint}>This reference document is available in the client folder on your PC.</Text>}</Card>)}{!assets.length && <Card><Empty icon="images-outline" title="No registered assets" body="Add client assets to the managed folder on your PC, then select this client again." /></Card>}
      {!!preview && <Card style={{ gap: 14 }}><BusinessMedia host={host} token={token} path={preview.url} kind={preview.kind} label={preview.name} onUnauthorized={onUnauthorized} /><Button label="Close asset preview" onPress={() => setPreview(null)} /></Card>}
    </Section>}
    {client && screen === "social-profiles" && <Section title={`${client.name} public profiles`}><Card style={{ gap: 16 }}><Text style={t.muted}>Save this client’s public links for manual publishing. No destination account is connected here.</Text>{[...platforms, "website"].map(name => <View key={name} style={{ gap: 10 }}><Field editable={!busy} label={`${name} public profile URL`} value={links[name] || ""} autoCapitalize="none" autoCorrect={false} onChangeText={v => { setLinks(d => ({ ...d, [name]: v })); mark("links"); }} />{!!links[name] && <Button label={`Open ${name} profile`} disabled={busy} onPress={() => { if (!/^https:\/\//i.test(links[name])) { setError("Use an HTTPS public profile URL."); return; } Linking.openURL(links[name]).catch(e => setError(e.message)); }} />}</View>)}<Button label="Save client public links" kind="primary" busy={busy} onPress={() => action(async () => { const public_handles = Object.fromEntries(Object.entries(links).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v)); const result = await request(`/clients/${client.id}`, { method: "PATCH", body: { public_handles } }); setClient(result.client); mark("links", false); }, "Public profiles saved for this client.")} /></Card></Section>}
  </ScrollView>;
}
function Platforms({ label, selected = [], onChange, disabled }) {
  return <View style={{ gap: 8 }}><Text style={t.label}>{label}</Text>{platforms.map(name => <View key={name} style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44 }}><Text style={t.muted}>{name}</Text><Switch disabled={disabled} accessibilityLabel={`${label}: ${name}`} value={selected.includes(name)} onValueChange={on => onChange(on ? [...selected, name] : selected.filter(p => p !== name))} /></View>)}</View>;
}
