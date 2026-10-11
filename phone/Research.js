import React, { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Linking, Pressable, Share, Text, View } from "react-native";
import { call } from "./api";
import { formatTime } from "./Desk";
import { Button, C, Card, Empty, Field, Pill, Section, t } from "./theme";

const RESEARCH_POLL_MS = 6000;
const plain = value => typeof value === "string" ? value : value == null ? "" : JSON.stringify(value, null, 2);
const copyText = value => typeof value === "string" ? value : Object.entries(value || {}).map(([key, part]) => `${key.replace(/_/g, " ")}: ${Array.isArray(part) ? part.join(" ") : plain(part)}`).join("\n\n");
const errorText = r => plain(r.data?.error || r.data?.detail) || `The PC answered ${r.status}. Try again.`;
export const safeSourceUrl = value => /^https?:\/\//i.test(String(value || "")) ? String(value) : null;

export function useResearch({ host, token, active, onUnauthorized }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const flight = useRef(null);
  const session = useRef(null);
  const currentSession = `${host || ""}:${token || ""}`;
  session.current = currentSession;
  const load = useCallback(() => {
    if (!host || !token) return Promise.resolve();
    if (flight.current?.key === currentSession) return flight.current.promise;
    setLoading(true);
    const promise = (async () => {
      try {
        const r = await call(host, "/api/research", { token });
        if (session.current !== currentSession) return;
        if (r.status === 401) { onUnauthorized(true); return; }
        if (!r.ok) throw new Error(errorText(r));
        setData(r.data); setError("");
      } catch (e) { if (session.current === currentSession) setError(e.message || "Research did not answer. Check your connection."); }
      finally {
        if (flight.current?.promise === promise) flight.current = null;
        if (session.current === currentSession) setLoading(false);
      }
    })();
    flight.current = { key: currentSession, promise };
    return promise;
  }, [host, token, currentSession, onUnauthorized]);
  useEffect(() => { setData(null); setError(""); }, [host, token]);
  useEffect(() => {
    if (!active || !host || !token) return;
    let alive = true, timer;
    const tick = async () => { await load(); if (alive) timer = setTimeout(tick, RESEARCH_POLL_MS); };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [active, host, token, load]);
  const request = async (path, options = {}) => {
    const r = await call(host, path, { token, ...options });
    if (r.status === 401) onUnauthorized(true);
    if (!r.ok || r.data?.ok === false) throw new Error(errorText(r));
    await load();
    return r.data;
  };
  return { data, error, loading, load, request };
}

function Source({ source, selected, onSelect, onError }) {
  const url = safeSourceUrl(source.url);
  return <View style={{ paddingVertical: 14, gap: 8 }}>
    <Text style={[t.body, { fontWeight: "600" }]}>{source.title || "Untitled source"}</Text>
    {!!source.summary && <Text style={t.muted}>{source.summary}</Text>}
    <Text style={t.faint}>{source.source || "Source"}{source.published ? ` · ${formatTime(source.published)}` : ""}</Text>
    <View style={{ flexDirection: "row", gap: 10, flexWrap: "wrap" }}>
      {onSelect && <Button small label={selected ? "Selected" : "Use in draft"} icon={selected ? "checkmark" : "add"} onPress={onSelect} />}
      {url && <Button small label="Read source" icon="open-outline" onPress={async () => { try { await Linking.openURL(url); } catch { onError("Could not open that source on this phone."); } }} />}
    </View>
  </View>;
}

function ResearchReview({ review }) {
  const [details, setDetails] = useState(false);
  if (typeof review === "string") return <View><Text style={t.label}>Judge’s review</Text><Text selectable style={[t.muted, { marginTop: 6 }]}>{review}</Text></View>;
  const warnings = Array.isArray(review.unsupported_claims) ? review.unsupported_claims : [];
  const approved = review.approved === true && review.grounded === true && !warnings.length;
  const audit = Object.entries(review).filter(([key]) => !["approved", "grounded", "reason", "unsupported_claims"].includes(key));
  return <Card tone={2} style={{ gap: 12 }}>
    <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}><Text style={[t.h2, { flex: 1 }]}>Judge’s review</Text><Pill label={approved ? "Approved" : "Needs review"} tone={approved ? "good" : "bad"} /></View>
    {!approved && <Text style={t.error}>This draft is held. Verify the claims below before using its copy.</Text>}
    {!!warnings.length && <View style={{ gap: 8 }}><Text style={t.label}>Claims to verify</Text>{warnings.map((warning, i) => <Text selectable key={i} style={t.error}>{plain(warning)}</Text>)}</View>}
    {!!review.reason && <View><Text style={t.label}>Model’s explanation</Text><Text selectable style={[t.muted, { marginTop: 6 }]}>{plain(review.reason)}</Text></View>}
    {!!audit.length && <>
      <Button small label={details ? "Hide review audit" : "Read review audit"} onPress={() => setDetails(!details)} accessibilityState={{ expanded: details }} />
      {details && audit.map(([key, value]) => <View key={key}><Text style={t.label}>{key.replace(/_/g, " ")}</Text><Text selectable style={[t.muted, { marginTop: 6 }]}>{plain(value)}</Text></View>)}
    </>}
  </Card>;
}

function Draft({ idea, onDelete, onError }) {
  const [open, setOpen] = useState(false);
  const j = idea.judgement || {};
  const sources = idea.sources || [];
  const posts = Object.entries(idea.posts || {});
  const exportText = [idea.topic, idea.angle, `Hook: ${idea.hook || ""}`, idea.script, ...posts.map(([platform, copy]) => `${platform}\n${copyText(copy)}`), "Sources", ...sources.map(s => `${s.title || "Source"}: ${s.url || ""}`)].filter(Boolean).join("\n\n");
  return <Card style={{ marginBottom: 16 }}>
    <Pressable accessibilityRole="button" accessibilityLabel={`${open ? "Close" : "Open"} draft: ${idea.topic}`} accessibilityState={{ expanded: open }} onPress={() => setOpen(!open)} style={({ pressed }) => ({ minHeight: 44, opacity: pressed ? 0.7 : 1 })}>
      <View style={{ flexDirection: "row", gap: 10, alignItems: "center" }}>
        <Text style={[t.h2, { flex: 1 }]}>{idea.topic || "Draft"}</Text>
        <Pill label={idea.status === "needs_review" ? "Needs review" : idea.status || "Unknown"} tone={idea.status === "ready" ? "good" : ["needs_review", "failed", "rejected"].includes(idea.status) ? "bad" : "plain"} />
      </View>
      {!!idea.angle && <Text style={[t.muted, { marginTop: 6 }]}>{idea.angle}</Text>}
    </Pressable>
    {!!idea.hook && <Text style={[t.body, { marginTop: 12 }]}>{idea.hook}</Text>}
    {!!idea.error && <Text style={[t.error, { marginTop: 10 }]}>{plain(idea.error)}</Text>}
    {open && <View style={{ gap: 16, marginTop: 16 }}>
      {!!Object.keys(j).length && <ResearchReview review={j} />}
      <View><Text style={t.label}>Script</Text><Text selectable style={[t.body, { marginTop: 6 }]}>{idea.script || "The script has not been produced yet."}</Text></View>
      {posts.map(([platform, copy]) => <View key={platform}><Text style={t.label}>{platform}</Text><Text selectable style={[t.body, { marginTop: 6 }]}>{copyText(copy)}</Text></View>)}
      <View><Text style={t.label}>Evidence</Text>{!sources.length ? <Text style={[t.muted, { marginTop: 6 }]}>No linked sources attached. Check the evidence before using this draft.</Text> : sources.map((s, i) => <Source key={s.id || i} source={s} onError={onError} />)}</View>
      <Text style={t.faint}>Draft text only. Review the claims and produce your video before publishing.</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
        <Button label="Share script & copy" icon="share-outline" disabled={!idea.script} onPress={async () => { try { await Share.share({ title: idea.topic, message: exportText }); } catch (e) { onError(e.message || "Could not share this draft."); } }} />
        <Button label="Delete draft" kind="danger" onPress={() => onDelete(idea)} />
      </View>
    </View>}
  </Card>;
}

export default function Research({ research }) {
  const { data, loading, error, load, request } = research;
  const [topic, setTopic] = useState("");
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");
  const working = !!data?.busy;
  useEffect(() => { if (data) setSelected(ids => ids.filter(id => (data.sources || []).some(s => s.id === id))); }, [data]);
  const action = async (key, path, options) => {
    if (busy) return;
    setBusy(key); setProblem(""); setNotice("");
    try { const result = await request(path, options); setNotice(`Research: ${result.status || "request accepted"}`); if (key === "draft") { setTopic(""); setSelected([]); } }
    catch (e) { setProblem(e.message || "The action did not complete. Try again."); }
    finally { setBusy(""); }
  };
  const remove = idea => Alert.alert("Delete this draft?", `Remove “${idea.topic || "Draft"}” and its generated copy.`, [{ text: "Keep", style: "cancel" }, { text: "Delete", style: "destructive", onPress: () => action("delete", `/api/research/ideas/${encodeURIComponent(idea.id)}`, { method: "DELETE" }) }]);
  const sources = data?.sources || [];
  return <>
    <View style={{ marginTop: 10, marginBottom: 24 }}><Text style={t.title}>Find a worthwhile angle</Text><Text style={[t.muted, { marginTop: 6 }]}>Researcher → director → scriptwriter → judge. Read the evidence and the verdict before using the copy.</Text></View>
    {!!(error || problem) && <Card style={{ marginBottom: 16 }}><Text accessibilityRole="alert" style={t.error}>{problem || error}</Text><Button label="Retry loading" busy={loading} onPress={load} style={{ marginTop: 12 }} /></Card>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={[t.muted, { marginBottom: 16 }]}>{notice}</Text>}
    {!data && loading && <ActivityIndicator accessibilityLabel="Loading research" color={C.ink2} style={{ marginBottom: 24 }} />}
    <Section title="Research desk"><Card>
      <View style={{ alignItems: "flex-start", gap: 10, marginBottom: 12 }}><Text style={t.h2}>Source discovery</Text><Pill label={data?.status || "Not loaded"} tone={working ? "live" : "plain"} /></View>
      <Text style={[t.muted, { marginBottom: 12 }]}>Updated: {formatTime(data?.updated)}. Previous sources stay visible if a refresh fails.</Text>
      <Button label="Refresh sources" icon="refresh" busy={busy === "refresh"} disabled={working || !!busy || !data} onPress={() => action("refresh", "/api/research/refresh", { method: "POST" })} />
      {working && <Text style={[t.faint, { marginTop: 10 }]}>The PC is working. You can leave this screen; progress is saved there.</Text>}
      {(data?.errors || []).map((e, i) => <Text key={i} style={[t.error, { marginTop: 10 }]}>{plain(e)}</Text>)}
    </Card></Section>
    <Section title="Draft a post"><Card>
      <Field label="Topic or question" value={topic} onChangeText={setTopic} multiline placeholder="What should your audience understand or care about?" accessibilityLabel="Topic or question for original content" />
      <Text style={[t.muted, { marginVertical: 12 }]}>{selected.length ? `${selected.length} selected sources will ground this draft.` : "Select sources below, or let the researcher use the available evidence."}</Text>
      <Button label="Build a researched draft" kind="primary" busy={busy === "draft"} disabled={!topic.trim() || working || !!busy || !data} onPress={() => action("draft", "/api/research/draft", { method: "POST", body: { topic: topic.trim(), ...(selected.length ? { source_ids: selected } : {}) } })} />
    </Card></Section>
    <Section title="Agent progress"><Card>
      {!data?.agents?.length ? <Text style={t.muted}>Agents report here when research begins.</Text> : data.agents.map((a, i) => <View key={a.role || i} style={{ paddingVertical: 10, gap: 6 }}><View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}><Text style={[t.body, { flex: 1, fontWeight: "600" }]}>{a.role}</Text><Pill label={a.status || "Unknown"} tone={a.status === "failed" ? "bad" : a.status === "running" ? "live" : "plain"} /></View>{!!a.model && <Text style={t.faint}>{a.model}</Text>}{!!a.detail && <Text style={t.muted}>{a.detail}</Text>}</View>)}
    </Card></Section>
    <Section title={`Drafts${data?.ideas ? ` · ${data.ideas.length}` : ""}`}>
      {!data?.ideas?.length ? <Card><Empty icon="document-text-outline" title="Your first angle starts here" body="Choose a topic and linked sources. Scripts and platform copy will be saved in this desk." /></Card> : data.ideas.map(idea => <Draft key={idea.id} idea={idea} onDelete={remove} onError={setProblem} />)}
    </Section>
    <Section title={`Sources${data?.sources ? ` · ${data.sources.length}` : ""}`}><Card>
      {!sources.length ? <Empty icon="search-outline" title="No sources gathered yet" body="Configure your niche and research feeds in Settings, then refresh sources." /> : sources.map(s => <Source key={s.id} source={s} selected={selected.includes(s.id)} onSelect={() => setSelected(ids => ids.includes(s.id) ? ids.filter(id => id !== s.id) : [...ids, s.id])} onError={setProblem} />)}
    </Card></Section>
  </>;
}
