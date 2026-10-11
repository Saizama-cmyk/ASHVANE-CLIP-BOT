import React from "react";
import { Text, View } from "react-native";
import { Button, C, Card, Empty, ListRow, Pill, Section, t } from "./theme";

export function formatTime(value) {
  if (!value) return "No update yet";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
}

export default function Desk({ state, research, onNavigate, onResearch, onPause, busy, loaded }) {
  const stages = state.stages?.counts || {};
  const samples = state.samples || [];
  const review = samples.filter(c => ["scheduled", "failed"].includes(c.stage));
  const platforms = Object.entries(state.scheduler?.platforms || {});
  const attention = platforms.filter(([, p]) => p.enabled && (!p.configured || p.error));
  const messages = Object.values(state.discovery?.messages || {}).filter(Boolean);
  const pending = ["queued", "qc", "transcribe", "clipability", "edit"].reduce((n, key) => n + Number(state.stages?.live?.[key] || 0), 0);
  return <>
    <View style={{ marginTop: 10, marginBottom: 24 }}>
      <Text style={t.title}>Your daily cut list</Text>
      <Text style={[t.muted, { marginTop: 6 }]}>Review the promising moments. Build an original post from sources. Check where it can go.</Text>
    </View>
    {!loaded ? <Card style={{ marginBottom: 24 }}><Text style={t.muted}>Waiting for the PC’s current desk…</Text></Card> : <>
      <Card style={{ marginBottom: 24 }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <Text style={t.h2}>Production</Text>
          <Pill label={state.status || "Unknown"} tone={state.status === "running" ? "good" : "plain"} />
        </View>
        <View style={{ flexDirection: "row", gap: 10 }}>
          {[[state.monitors?.length || 0, "Watching"], [pending, "Processing"], [stages.scheduled || 0, "Ready"]].map(([value, label]) => <View key={label} style={{ flex: 1 }}><Text style={t.num}>{value}</Text><Text style={t.muted}>{label}</Text></View>)}
        </View>
        <Text style={[t.faint, { marginTop: 12 }]}>{Number(stages.posted || 0)} posted · {Number(stages.rejected || 0)} rejected in the last {state.stages?.window_h ?? "—"} hours</Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 16 }}>
          <Button label="Review clips" kind="primary" onPress={() => onNavigate("clips")} grow />
          <Button label={state.manual_paused ? "Resume capture" : "Pause capture"} busy={busy} onPress={onPause} />
        </View>
      </Card>
      {!!(state.ai?.error || state.ai?.vision_error || attention.length || messages.length) && <Section title="Needs attention"><Card>
        {[state.ai?.error, state.ai?.vision_error].filter(Boolean).map((message, i) => <Text key={i} style={[t.error, { marginBottom: 10 }]}>{String(message)}</Text>)}
        {messages.map((message, i) => <Text key={`setup-${i}`} style={[t.muted, { marginBottom: 10 }]}>{String(message)}</Text>)}
        {attention.map(([name, p]) => <Text key={name} style={[t.muted, { marginBottom: 10 }]}>{name}: {p.error || p.reason || "Connection needs setup"}</Text>)}
        <Button label="Open settings" onPress={() => onNavigate("settings")} />
      </Card></Section>}
      <Section title="Next to review"><Card pad={false}>
        {!review.length ? <Empty icon="film-outline" title="No cuts waiting here" body="Ready clips and failed jobs appear as your streams are processed." /> : review.slice(0, 4).map((c, i) => <ListRow key={c.id} first={!i} icon="film-outline" title={c.verdict?.title || c.event?.target?.display_name || c.id} sub={c.error || c.verdict?.reason || c.stage} right={<Pill label={c.stage} tone={c.stage === "failed" ? "bad" : "plain"} />} onPress={() => onNavigate("clips")} />)}
      </Card></Section>
      <Section title="Publishing connections"><Card pad={false}>
        {!platforms.length ? <Empty title="No publishing state yet" body="Connect accounts in Settings on your PC." /> : platforms.map(([name, p], i) => <ListRow key={name} first={!i} title={name} sub={p.error || p.reason || (p.enabled ? `${p.posted_24h} / ${p.cap} posts in 24 hours` : "Disabled in settings")} right={<Pill label={!p.enabled ? "Off" : !p.configured ? "Set up" : p.busy ? "Posting" : p.ready_now ? "Ready" : "Waiting"} tone={p.enabled && p.configured && p.ready_now ? "good" : p.error ? "bad" : "plain"} />} onPress={() => onNavigate("settings")} />)}
      </Card></Section>
      <Section title="Recent post results"><Card pad={false}>
        {!state.posts?.length ? <Empty icon="send-outline" title="No post results yet" body="Successful and failed publishing attempts will appear here." /> : state.posts.slice(0, 4).map((p, i) => <ListRow key={p.id || i} first={!i} title={p.platform || "Platform"} sub={p.error || formatTime(p.created_at || p.posted_at)} right={<Pill label={p.status || "Unknown"} tone={p.status === "ok" ? "good" : "bad"} />} />)}
      </Card></Section>
    </>}
    <Section title="Original content"><Card>
      <Text style={t.h2}>One angle, linked evidence</Text>
      <Text style={[t.muted, { marginTop: 6, marginBottom: 16 }]}>{research ? `${research.sources?.length || 0} sources · ${research.ideas?.length || 0} drafts · ${research.status || "Unknown"}` : "Research a topic, review the script, then share the copy for each platform."}</Text>
      <Button label="Open research" icon="search-outline" onPress={onResearch} />
    </Card></Section>
  </>;
}
