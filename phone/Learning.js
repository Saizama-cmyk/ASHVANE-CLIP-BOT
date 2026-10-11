import React, { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { Button, Card, Field, t } from "./theme";
import { useWorkspace } from "./workspace";

export default function Learning({ host, token, onUnauthorized, business, clientId, profileId, example, onDirtyChange, active = true }) {
  const { request, action, busy, error, notice } = useWorkspace({ host, token, onUnauthorized }, `/api/creative-memory/${business}`);
  const [open, setOpen] = useState(false), [data, setData] = useState(null), [guidance, setGuidance] = useState(""), [notes, setNotes] = useState("");
  const [guidanceDirty, setGuidanceDirty] = useState(false), [feedbackExample, setFeedbackExample] = useState(null);
  const [boundProfile, setBoundProfile] = useState("");
  const scope = { ...(business !== "social" && boundProfile ? { account_profile_id: boundProfile } : {}), ...(clientId ? { client_id: clientId } : {}), ...(profileId ? { profile_id: profileId } : {}) };
  const query = Object.entries(scope).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  useEffect(() => { onDirtyChange?.(guidanceDirty || !!notes.trim()); }, [guidanceDirty, notes, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  useEffect(() => {
    if (!open || !active) return;
    if (business === "social" && data) return;
    if (guidanceDirty || notes.trim()) return;
    action(async () => { const memory = await request(business === "social" && query ? `?${query}` : ""); setData(memory); setGuidance(memory.guidance || ""); setBoundProfile(memory.account_profile_id || ""); }, "Preferences loaded.");
  }, [open, active, business, request]);
  const refresh = async () => { const memory = await request(query ? `?${query}` : ""); setData(memory); if (!data && !guidanceDirty) setGuidance(memory.guidance || ""); return memory; };
  const feedback = verdict => action(async () => {
    await request("/feedback", { method: "POST", body: { ...scope, ...(business !== "social" && (feedbackExample || example)?.account_profile_id ? { account_profile_id: (feedbackExample || example).account_profile_id } : {}), verdict, notes, ...((feedbackExample || example) ? { example: { title: String((feedbackExample || example).title || "").slice(0, 300), text: String((feedbackExample || example).text || "").slice(0, 4000) } } : {}) } });
    setNotes(""); setFeedbackExample(null); await refresh();
  }, "Feedback saved for future work in this scope.");
  return <View style={{ marginTop: 16, gap: 12 }}><Button label={open ? "Close learning & feedback" : "Learning & feedback"} onPress={() => setOpen(v => !v)} />
    {open && <Card style={{ gap: 14 }}><Text style={t.h2}>Creative preferences</Text><Text style={t.faint}>{business === "social" ? "For this client and selected style profile." : `For this business and account profile${boundProfile ? ` (${boundProfile})` : ""}.`} Your guidance and feedback shape future suggestions.</Text>
      {!!error && <Text accessibilityRole="alert" style={t.error}>{error}</Text>}{!!notice && <Text accessibilityLiveRegion="polite" style={t.faint}>{notice}</Text>}
      {business !== "social" && <Button label="Load active profile learning" disabled={busy || guidanceDirty || !!notes.trim()} onPress={() => action(async () => { const memory = await request(""); setBoundProfile(memory.account_profile_id || ""); setData(memory); setGuidance(memory.guidance || ""); }, "Active profile learning loaded.")} />}
      {business !== "social" && (guidanceDirty || !!notes.trim()) && <Text style={t.faint}>These edits stay bound to the profile that loaded them. Save them before loading another profile.</Text>}
      <Field label="Learning guidance" value={guidance} multiline maxLength={4000} editable={!!data && !busy} onChangeText={value => { setGuidance(value); setGuidanceDirty(true); }} />
      <Button label="Save learning guidance" busy={busy} disabled={!data || !guidanceDirty} onPress={() => action(async () => { await request("", { method: "PUT", body: { ...scope, guidance } }); setGuidanceDirty(false); await refresh(); }, "Your guidance was saved.")} />
      {(data?.reference_guidance || []).map((reference, i) => <View key={reference.asset_id || i} style={{ gap: 6 }}><Text style={t.label}>{reference.name || "Reference"} · {reference.status || "Saved"}</Text>{!!reference.summary && <Text style={t.faint}>{reference.summary}</Text>}{(reference.rules || []).map((rule, j) => <Text key={j} style={t.faint}>• {rule}</Text>)}</View>)}
      <Button label="Refresh learned references" disabled={busy} onPress={() => action(refresh, "Learned references refreshed.")} />
      <Text style={t.faint}>{Array.isArray(data?.feedback) ? data.feedback.length : 0} feedback notes saved</Text>
      {!!example && <Text style={t.label}>Feedback on: {(feedbackExample || example).title || "Current draft"}</Text>}
      {!!(feedbackExample || example)?.account_profile_id && business !== "social" && <Text style={t.faint}>Output feedback stays with account profile {(feedbackExample || example).account_profile_id}.</Text>}
      <Field label="What should it learn?" value={notes} multiline maxLength={4000} editable={!busy} onChangeText={value => { if (!notes) setFeedbackExample(example || null); setNotes(value); }} placeholder="What worked, what missed, or what to change next time" />
      <View style={{ flexDirection: "row", gap: 10 }}><Button label="Liked it" disabled={!data || busy} onPress={() => feedback("liked")} style={{ flex: 1 }} /><Button label="Disliked it" disabled={!data || busy} onPress={() => feedback("disliked")} style={{ flex: 1 }} /></View>
    </Card>}
  </View>;
}
