import React, { useState } from "react";
import { Text, View } from "react-native";
import { Button, Card, Pill, t } from "./theme";
import { useWorkspace } from "./workspace";
export default function PhoneSetup({ host, token, onUnauthorized, latency }) {
  const { request, action, busy, error } = useWorkspace({ host, token, onUnauthorized }, "/api");
  const [data, setData] = useState(null);
  return <Card style={{ gap: 14 }}><Text style={t.h2}>Business setup checker</Text><Text style={t.muted}>Check local models and tools for all four businesses. A stopped business is paused; installed tools alone do not verify production.</Text><Button label="Check four businesses" busy={busy} disabled={!host || !token} onPress={() => action(async () => setData(await request("/setup", { timeout: 65000 })))} />
    {!!error && <Text accessibilityRole="alert" style={t.error}>{error}</Text>}
    {!!data?.shared?.message && <Text style={t.faint}>{data.shared.message}</Text>}
    {(data?.businesses || []).map(group => <View key={group.id} style={{ gap: 10, marginTop: 8 }}><Text style={t.h2}>{group.name}</Text><Pill label={!group.enabled ? "Stopped" : group.status || (group.ready ? "Ready" : "Setup needed")} tone={group.enabled && group.ready ? "good" : "plain"} /><Text style={t.muted}>{group.message}</Text>{(group.items || []).map(item => <View key={item.id} style={{ gap: 4 }}><Text style={t.label}>{item.label || item.name || item.id} · {item.ok ? "Passed" : item.required ? "Needs attention" : "Optional"}</Text><Text style={t.faint}>{item.message || item.detail}</Text></View>)}</View>)}
    {!!latency && <View style={{ gap: 8 }}><Text style={t.h2}>Clip processing time</Text><Text style={t.faint}>Measured inside Ashvane. Source-to-stream delay is unavailable.</Text><Text style={t.muted}>Transcription: {latency.transcription?.active || 0} active · {latency.transcription?.waiting || 0} waiting</Text>{(latency.active_jobs || []).map(job => <Text key={job.id} style={t.faint}>{job.title || job.id} · {job.phase} · {Math.round(job.age_s || 0)}s total · {Math.round(job.phase_age_s || 0)}s in phase</Text>)}</View>}
  </Card>;
}
