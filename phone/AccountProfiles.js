import React, { useEffect, useState } from "react";
import { Alert, Linking, Platform, ScrollView, Text, View } from "react-native";
import { Button, Card, Field, Pill, Section, t } from "./theme";
import { Options } from "./Music";
import { useWorkspace } from "./workspace";

const names = { clips: "Surge", stories: "Hollow", music: "Resonance" };
const platforms = ["youtube", "tiktok", "instagram", "facebook", "discord"];
const fields = [
  ["youtube", "YouTube", [["youtube_client_id", "OAuth client ID"], ["youtube_client_secret", "OAuth client secret", true]]],
  ["tiktok", "TikTok", [["tiktok_client_key", "Client key"], ["tiktok_client_secret", "Client secret", true], ["tiktok_redirect_uri", "Redirect URI"]]],
  ["instagram", "Instagram", [["instagram_user_id", "Instagram user ID"], ["instagram_token", "Instagram access token", true]]],
  ["facebook", "Facebook", [["facebook_page_id", "Facebook Page ID"], ["facebook_page_token", "Facebook Page token", true]]],
  ["discord", "Discord", [["discord_webhook", "Discord webhook URL", true]]],
];
const buffers = new Map();
const confirm = (message, run) => {
  if (Platform.OS === "web") { if (globalThis.confirm(message)) run(); }
  else Alert.alert("Confirm account change", message, [{ text: "Keep", style: "cancel" }, { text: "Continue", style: "destructive", onPress: run }]);
};
export default function AccountProfiles({ business, host, token, onUnauthorized, onDirtyChange, onChanged }) {
  const key = `${host}:${token}:${business}`, restored = buffers.get(key) || {};
  const { request, action, busy, error, setError, notice } = useWorkspace({ host, token, onUnauthorized }, `/api/account-profiles/${business}`);
  const [data, setData] = useState(null), [selectedId, setSelectedId] = useState(restored.selectedId || ""), [draft, setDraft] = useState(restored.draft || {}), [accountDraft, setAccountDraft] = useState(restored.accountDraft || {});
  const [newName, setNewName] = useState(restored.newName || ""), [urls, setUrls] = useState(restored.urls || {}), [authLinks, setAuthLinks] = useState({});
  const dirty = !!Object.keys(draft).length || !!Object.keys(accountDraft).length || !!newName.trim() || Object.values(urls).some(Boolean);
  const selected = data?.profiles?.find(row => row.id === selectedId), active = selectedId === data?.active_profile_id;
  const load = async () => { const next = await request(""); setData(next); setSelectedId(id => id || next.active_profile_id); };
  useEffect(() => { load().catch(e => setError(e.message)); }, [request]);
  useEffect(() => { buffers.set(key, { selectedId, draft, accountDraft, newName, urls }); onDirtyChange?.(dirty); }, [key, selectedId, draft, accountDraft, newName, urls, dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const changed = async () => { await load(); await onChanged?.(); };
  const select = id => { if (dirty) { setError("Save or discard these account edits before selecting another profile."); return; } setSelectedId(id); setAuthLinks({}); setError(""); };
  const save = () => action(async () => {
    const secrets = new Set(fields.flatMap(([, , entries]) => entries.filter(([, , secret]) => secret).map(([name]) => name)));
    const accounts = Object.fromEntries(Object.entries(accountDraft).filter(([name, value]) => !secrets.has(name) || value.trim()));
    await request(`/${selectedId}`, { method: "PATCH", body: { ...draft, ...(Object.keys(accounts).length ? { accounts } : {}) } }); setDraft({}); setAccountDraft({}); await changed();
  }, "Account profile saved.");
  const connection = (platform, operation, body = {}) => action(async () => {
    if (!active || Object.keys(draft).length || Object.keys(accountDraft).length) throw new Error("Save edits and activate this profile before connecting.");
    const result = await request(`/${selectedId}/${platform}/${operation}`, { method: "POST", body });
    if (operation === "open") { setAuthLinks(links => ({ ...links, [platform]: result.url })); if (!result.opened) throw new Error("The PC browser could not open. Use the sign-in link below."); }
    if (operation === "paste") setUrls(values => ({ ...values, [platform]: "" }));
    await changed();
  }, operation === "open" ? "Finish sign-in in your PC browser." : "Profile connection updated.");
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 16, paddingBottom: 36 }}>
    <Section title={`${names[business]} accounts`}><Text style={t.muted}>{business === "music" ? "Artist profiles and public links for Resonance. Distribution is manual; no publishing account is connected here." : "Each named profile has its own channels and sign-in. Queued work stays with its original profile."}</Text></Section>
    {!!error && <Card style={{ gap: 12, marginBottom: 16 }}><Text accessibilityRole="alert" style={t.error}>{error}</Text><Button label="Refresh account profiles" disabled={busy} onPress={() => action(load, "Profiles refreshed.")} /></Card>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={[t.muted, { marginBottom: 16 }]}>{notice}</Text>}
    {!!data?.error && <Text style={t.error}>{data.error}</Text>}
    {data && <Section title="Account profiles"><Card style={{ gap: 14 }}>
      <Options label="Selected account profile" options={data.profiles.map(row => [row.id, `${row.name}${row.id === data.active_profile_id ? " · Active" : ""}`])} value={selectedId} disabled={busy} onChange={select} />
      {!!data.queue_policy && <Text style={t.faint}>{typeof data.queue_policy === "string" ? data.queue_policy : "Queued work remains bound to its original profile."}</Text>}
      <Field label="New account profile name" value={newName} maxLength={120} editable={!busy} onChangeText={setNewName} />
      <Button label="Create account profile" disabled={busy || !newName.trim() || Object.keys(draft).length > 0 || Object.keys(accountDraft).length > 0} onPress={() => action(async () => { const next = await request("", { method: "POST", body: { name: newName.trim() } }); setData(next); const created = next.profiles.find(row => !data.profiles.some(old => old.id === row.id)); setSelectedId(created?.id || next.active_profile_id); setNewName(""); setUrls({}); }, "Profile created. Activate it when ready.")} />
    </Card></Section>}
    {selected && <>
      <Section title={`Editing ${selected.name}`}><Card style={{ gap: 14 }}><Pill label={active ? "Active profile" : "Inactive profile"} tone={active ? "good" : "plain"} />
        <Field label="Account profile name" value={draft.name ?? selected.name} maxLength={120} editable={!busy} onChangeText={name => setDraft(d => ({ ...d, name }))} />
        <Field label="Account profile description" value={draft.description ?? selected.description ?? ""} multiline maxLength={2000} editable={!busy} onChangeText={description => setDraft(d => ({ ...d, description }))} />
        <Button label="Activate selected profile" disabled={busy || active || dirty} onPress={() => action(async () => { const next = await request(`/${selectedId}/activate`, { method: "POST", body: {} }); setData(next); setUrls({}); setAuthLinks({}); await onChanged?.(); }, "Active account profile changed.")} />
        {dirty && <Text style={t.faint}>Save or discard account edits before activating another profile.</Text>}
      </Card></Section>
      {business !== "music" && fields.map(([platform, title, entries]) => { const status = selected.connections?.[platform]; return <Section key={platform} title={title}><Card style={{ gap: 14 }}><Pill label={status?.ready ? "Connected" : "Setup needed"} tone={status?.ready ? "good" : "plain"} />{!!status?.account_label && <Text style={t.body}>{status.account_label}</Text>}{!!status?.account_id && <Text selectable style={t.faint}>{status.account_id}</Text>}{!!status?.reason && <Text style={t.faint}>{status.reason}</Text>}
        {entries.map(([name, label, secret]) => <Field key={name} label={label} value={accountDraft[name] ?? (secret ? "" : selected.accounts?.[name] || "")} placeholder={secret && selected.accounts?.[name] ? `Saved ${selected.accounts[name]}` : ""} secureTextEntry={!!secret} autoCapitalize="none" autoCorrect={false} maxLength={2000} editable={!busy} onChangeText={value => setAccountDraft(d => ({ ...d, [name]: value }))} />)}
        {["youtube", "tiktok"].includes(platform) && <><Button label={`Connect ${title} on PC`} disabled={busy || !active} onPress={() => connection(platform, "open")} />{!!authLinks[platform] && <Button label={`Open ${title} sign-in on this phone`} onPress={() => Linking.openURL(authLinks[platform]).catch(e => setError(e.message))} />}<Text style={t.faint}>If the browser cannot reach your PC, paste the full return-page address below.</Text><Field label={`${title} return URL`} value={urls[platform] || ""} maxLength={10000} editable={!busy && active} autoCapitalize="none" autoCorrect={false} onChangeText={value => setUrls(values => ({ ...values, [platform]: value }))} /><Button label={`Finish ${title} connection`} disabled={busy || !active || !urls[platform]?.trim()} onPress={() => connection(platform, "paste", { url: urls[platform].trim() })} /><Button label={`Disconnect ${title}`} disabled={busy || !active || !status?.ready} onPress={() => confirm(`Disconnect ${title} from ${selected.name}?`, () => connection(platform, "disconnect"))} /></>}
      </Card></Section>; })}
      <Section title={business === "music" ? "Public artist links" : "Public profile links"}><Card style={{ gap: 14 }}>{platforms.map(platform => <Field key={platform} label={`${platform} public profile URL`} value={draft.public_handles?.[platform] ?? selected.public_handles?.[platform] ?? ""} maxLength={2000} editable={!busy} autoCapitalize="none" autoCorrect={false} onChangeText={value => setDraft(d => ({ ...d, public_handles: { ...selected.public_handles, ...d.public_handles, [platform]: value } }))} />)}</Card></Section>
      <Button label="Save account profile" kind="primary" busy={busy} disabled={!Object.keys(draft).length && !Object.keys(accountDraft).length} onPress={save} />
      {business !== "music" && <Button label="Cancel pending sign-in" disabled={busy || !active} onPress={() => action(async () => { await request(`/${selectedId}/cancel-signin`, { method: "POST", body: {} }); setUrls({}); setAuthLinks({}); await changed(); }, "Pending sign-in cancelled.")} style={{ marginTop: 12 }} />}
      {dirty && <Button label="Discard account edits" disabled={busy} onPress={() => confirm("Discard these unsaved account profile edits?", () => { setDraft({}); setAccountDraft({}); setNewName(""); setUrls({}); })} style={{ marginTop: 12 }} />}
    </>}
  </ScrollView>;
}
