import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Linking, ScrollView, Text, View } from "react-native";
import { call } from "./api";
import { Button, Card, Field, Pill, Section, t } from "./theme";

const groups = [
  ["youtube", "YouTube", [["youtube_client_id", "OAuth client ID"], ["youtube_client_secret", "OAuth client secret", true]]],
  ["tiktok", "TikTok", [["tiktok_client_key", "Client key"], ["tiktok_client_secret", "Client secret", true], ["tiktok_redirect_uri", "Redirect URI"]]],
  ["instagram", "Instagram", [["instagram_user_id", "Instagram user ID"], ["instagram_token", "Instagram access token", true]]],
  ["facebook", "Facebook", [["facebook_page_id", "Facebook Page ID"], ["facebook_page_token", "Facebook Page token", true]]],
  ["discord", "Discord", [["discord_webhook", "Discord webhook URL", true]]],
];

export default function StoryAccounts({ host, token, onUnauthorized, onChanged, onDirtyChange }) {
  const [data, setData] = useState(null), [draft, setDraft] = useState({}), [urls, setUrls] = useState({}), [authLinks, setAuthLinks] = useState({});
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => { onDirtyChange?.(Object.keys(draft).length > 0); }, [draft, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const request = useCallback(async (suffix = "", options = {}) => {
    const r = await call(host, `/api/stories/accounts${suffix}`, { token, ...options });
    if (r.status === 401) onUnauthorized(true);
    if (!r.ok || r.data?.ok === false) throw new Error(r.data?.detail || r.data?.error || "Story accounts did not answer.");
    return r.data;
  }, [host, token, onUnauthorized]);
  const load = useCallback(async () => {
    try { setData(await request()); setError(""); } catch (e) { setError(e.message); }
  }, [request]);
  useEffect(() => { setData(null); setDraft({}); load(); }, [load]);
  const action = async (run, message) => {
    setBusy(true); setError(""); setNotice("");
    try { await run(); await load(); await onChanged?.(); setNotice(message); }
    catch (e) { setError(e.message || "Account update failed."); }
    finally { setBusy(false); }
  };
  const save = () => action(async () => {
    // Blank secrets preserve the saved value. Never submit server masks.
    const secrets = new Set(groups.flatMap(([, , fields]) => fields.filter(([, , secret]) => secret).map(([key]) => key)));
    const changes = Object.fromEntries(Object.entries(draft).filter(([key, value]) => !secrets.has(key) || value.trim()));
    await request("", { method: "PUT", body: changes }); setDraft({});
  }, "Story accounts saved.");
  return <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: 16, paddingBottom: 36 }}>
    <Section title="Story accounts"><Text style={t.muted}>These channels and credentials belong to Hollow. Connect Hollow’s own channels separately from Surge. Saved secrets stay on your PC; leave their fields blank to keep them.</Text></Section>
    {!!error && <Card style={{ marginBottom: 16 }}><Text accessibilityRole="alert" style={t.error}>{error}</Text><Button label="Retry accounts" onPress={load} /></Card>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={t.muted}>{notice}</Text>}
    {!data && !error && <ActivityIndicator accessibilityLabel="Loading story accounts" />}
    {data && groups.map(([id, label, fields]) => {
      const destination = data.destinations?.find(d => d.id === id), oauth = ["youtube", "tiktok"].includes(id);
      return <Section key={id} title={label}><Card style={{ gap: 14 }}>
        <Pill label={destination?.ready ? "Connected" : "Setup needed"} tone={destination?.ready ? "good" : "plain"} />
        {!!destination?.account_label && <Text style={t.body}>{destination.account_label}</Text>}
        {!!destination?.account_id && <Text selectable style={t.faint}>{destination.account_id}</Text>}
        {!!destination?.reason && <Text style={t.faint}>{destination.reason}</Text>}
        {data.app_credentials?.[id]?.inherited && <Text style={t.faint}>Uses shared app credentials. Your connected Story account is separate.</Text>}
        {fields.map(([key, title, secret]) => <Field key={key} label={title} value={draft[key] ?? (secret ? "" : data.accounts?.[key] || "")} placeholder={secret && data.accounts?.[key] ? `Saved ${data.accounts[key]}` : ""} secureTextEntry={!!secret} autoCapitalize="none" autoCorrect={false} editable={!busy} onChangeText={value => setDraft(d => ({ ...d, [key]: value }))} />)}
        {oauth && <>
          <Button label={`Connect ${label} on PC`} disabled={busy} onPress={() => action(async () => {
            if (Object.keys(draft).length) throw new Error("Save your credential edits before connecting.");
            const result = await request(`/${id}/open`, { method: "POST", body: {} });
            if (!result.url) throw new Error("The PC did not return a sign-in URL.");
            setAuthLinks(links => ({ ...links, [id]: result.url }));
            if (result.opened === false) throw new Error("The PC browser could not open. Use the sign-in link below.");
          }, "Finish sign-in in your PC browser.")} />
          {!!authLinks[id] && <Button label="Open sign-in on this phone" disabled={busy} onPress={() => Linking.openURL(authLinks[id]).catch(e => setError(e.message))} />}
          <Text style={t.faint}>After signing in, paste the full return-page address here if the browser cannot reach your PC.</Text>
          <Field label={`${label} return URL`} value={urls[id] || ""} onChangeText={value => setUrls(u => ({ ...u, [id]: value }))} autoCapitalize="none" autoCorrect={false} editable={!busy} />
          <Button label="Finish connection" disabled={busy || !urls[id]?.trim()} onPress={() => action(async () => { await request(`/${id}/paste`, { method: "POST", body: { url: urls[id].trim() } }); setUrls(u => ({ ...u, [id]: "" })); }, `${label} story connection updated.`)} />
          <Button label={`Disconnect ${label}`} disabled={busy || !data.oauth?.[id]} onPress={() => action(() => request(`/${id}/disconnect`, { method: "POST" }), `${label} story account disconnected.`)} />
        </>}
      </Card></Section>;
    })}
    <Button label="Save story accounts" kind="primary" busy={busy} disabled={!data || !Object.keys(draft).length} onPress={save} />
  </ScrollView>;
}
