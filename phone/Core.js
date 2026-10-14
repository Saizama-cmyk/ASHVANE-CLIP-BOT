/** Shared maintenance controls. Operational text comes only from authenticated PC records. */
import React, {useCallback, useEffect, useRef, useState} from "react";
import {AccessibilityInfo, ActivityIndicator, Pressable, RefreshControl, ScrollView, Switch, Text, View} from "react-native";
import {call} from "./api";
import CoreScene from "./CoreScene";
import {GravityMark} from "./Portal";
import {Button, C, Card, Empty, Field, Icon, Pill, Section, t} from "./theme";

const POLL_MS = 6000;
const rows = value => Array.isArray(value) ? value : [];
const label = value => String(value || "Not reported").replace(/_/g," ");
const time = value => { const date = new Date(typeof value === "number" ? value * 1000 : value); return value && Number.isFinite(date.getTime()) ? date.toLocaleString() : "Time not reported"; };
function taskText(value) {
  if (!value) return "No current task reported.";
  if (typeof value !== "string") return "A task is reported; no description is available.";
  try { const data = JSON.parse(value); return [data.task,data.goal,data.owner_goal].find(item=>typeof item==="string"&&item.trim()) || (data.verified_capabilities ? "Checking installed capabilities and observed work." : "A structured investigation task is assigned."); }
  catch { return value; }
}

export default function Core({host, token, active, onUnauthorized}) {
  const [snapshot,setSnapshot] = useState(null), [selected,setSelected] = useState(""), [goal,setGoal] = useState("");
  const [error,setError] = useState(""), [notice,setNotice] = useState(""), [busy,setBusy] = useState(""), [refreshing,setRefreshing] = useState(false), [reduced,setReduced] = useState(true);
  const controllers = useRef(new Set()), live = useRef(false), inFlight = useRef(null), mutation = useRef(null), generation = useRef(0);
  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled().then(value => { if (mounted) setReduced(value); }).catch(() => {});
    const listener = AccessibilityInfo.addEventListener("reduceMotionChanged",setReduced);
    return () => { mounted = false; listener.remove(); };
  }, []);
  const request = useCallback(async (path="", options={}) => {
    const controller = new AbortController(); controllers.current.add(controller);
    try {
      const r = await call(host, `/api/supervisor${path}`, {token,timeout:65000,...options,signal:controller.signal});
      if (r.status === 401) { onUnauthorized?.(true); throw new Error("Your PC session ended. Sign in again."); }
      if (!r.ok || r.data?.ok === false) throw new Error(typeof r.data?.detail === "string" ? r.data.detail : r.data?.error || `The PC answered ${r.status}. Retry after checking Core on your PC.`);
      return r.data;
    } finally { controllers.current.delete(controller); }
  }, [host, token, onUnauthorized]);
  const load = useCallback(() => {
    if (inFlight.current) return inFlight.current;
    const currentGeneration = generation.current;
    const operation = (async () => {
      try {
        const data = await request();
        if (!Array.isArray(data.agents) || typeof data.enabled !== "boolean") throw new Error("Core returned an incomplete status. Retry after updating the PC app.");
        if (!live.current || generation.current !== currentGeneration) return;
        setSnapshot(data); setError("");
        setSelected(current => data.agents.some(row=>row.id===current) ? current : data.agents[0]?.id || "");
      } catch (e) { if (live.current && generation.current === currentGeneration && e.name !== "AbortError") setError(e.message || "Core could not reach the PC. Retry."); }
      finally { if (inFlight.current === operation) inFlight.current = null; }
    })();
    inFlight.current = operation; return operation;
  }, [request]);
  useEffect(() => {
    generation.current++;
    mutation.current = null; setBusy("");
    live.current = active && !!host && !!token;
    if (!live.current) return;
    let timer;
    const tick = async () => { await load(); if (live.current) timer = setTimeout(tick,POLL_MS); };
    tick();
    return () => { live.current = false; generation.current++; clearTimeout(timer); controllers.current.forEach(controller=>controller.abort()); inFlight.current = null; };
  }, [host,token,active,load]);
  const act = async (path,body,message) => {
    if (mutation.current) return;
    const operation = Symbol("Core action"); mutation.current = operation;
    setBusy(path); setError(""); setNotice("");
    const currentGeneration = generation.current;
    try { await request(path,{method:"POST",body}); if (!live.current || generation.current !== currentGeneration) return; setNotice(message); await load(); }
    catch (e) { if (live.current && generation.current === currentGeneration && e.name !== "AbortError") setError(e.message || "The action failed. Retry."); }
    finally { if (mutation.current === operation) { mutation.current = null; if (live.current) setBusy(""); } }
  };
  const agents = rows(snapshot?.agents), agent = agents.find(row=>row.id===selected);
  const receipts = rows(snapshot?.work_receipts), selectedReceipts = receipts.filter(row=>row.role===selected);
  const completedTools = receipts.filter(row=>row.kind === "tool_completed").length, failedTools = receipts.filter(row=>row.kind === "tool_failed").length;
  const latestGoal = rows(snapshot?.goals).filter(row=>row.agent===selected).at(-1);
  const blocked = snapshot?.blocking_reason || snapshot?.error;
  const waiting = snapshot?.state === "waiting_for_business";
  const job = snapshot?.active_job || snapshot?.pending_job;
  return <ScrollView contentContainerStyle={{padding:20,paddingBottom:40}} refreshControl={<RefreshControl tintColor={C.ember} refreshing={refreshing} onRefresh={async()=>{setRefreshing(true);try{await load();}finally{setRefreshing(false);}}} />}>
    <View style={{marginBottom:28}}><Text style={[t.faint,{color:C.ember}]}>Shared supervisor</Text><Text style={[t.title,{fontSize:36,lineHeight:42,marginTop:6}]}>The Core</Text><Text style={[t.muted,{marginTop:10}]}>One center. Independent specialists. Inspect the work behind every signal.</Text></View>
    {!!error && <Card style={{backgroundColor:C.badSoft,marginBottom:20,gap:14}}><Text accessibilityLiveRegion="polite" style={t.error}>{error}</Text><Button label="Retry Core connection" icon="refresh-outline" onPress={load} /></Card>}
    {!!notice && <Text accessibilityLiveRegion="polite" style={[t.muted,{color:C.good,marginBottom:20}]}>{notice}</Text>}
    {!snapshot && !error && <Card style={{gap:14,marginBottom:28}}><ActivityIndicator color={C.ember} /><Text style={t.muted}>Reading the supervisor's actual state from your PC…</Text></Card>}
    {snapshot && <>
      <Card style={{marginBottom:28}}>
        <View style={{flexDirection:"row",alignItems:"center",gap:14}}><View style={{flex:1}}><Text style={t.h2}>Master switch</Text><Text style={[t.faint,{marginTop:6}]}>{snapshot.enabled ? "Local improvement work is enabled." : "Supervisor is off. Records remain available."}</Text></View><Switch accessibilityLabel="Supervisor master switch" accessibilityState={{busy:busy==="/master"}} disabled={!!busy} value={snapshot.enabled} onValueChange={enabled=>act("/master",{enabled},enabled?"Supervisor enabled on your PC.":"Supervisor stopped; owned work is cancelling or draining.")} trackColor={{false:C.s4,true:C.ember}} thumbColor={snapshot.enabled?C.bg:C.ink2} /></View>
        <View style={{flexDirection:"row",flexWrap:"wrap",gap:10,marginTop:20}}><Pill label={label(snapshot.state)} tone={blocked?"bad":snapshot.enabled?"live":"plain"} /><Pill label={`${agents.length} reported agents`} /></View>
        {!!blocked && <View style={{marginTop:20,paddingLeft:14,borderLeftWidth:2,borderColor:C.bad}}><Text style={[t.label,{color:C.bad}]}>Current blocker</Text><Text style={[t.body,{marginTop:6}]}>{String(blocked)}</Text>{!!snapshot.blocking_since && <Text style={[t.faint,{marginTop:6}]}>Since {time(snapshot.blocking_since)}</Text>}</View>}
      </Card>
      <Section title="Agent constellation" right={<Pill label={reduced?"Static view":"Interactive"} />}>
        {!reduced && active && agents.length ? <CoreScene host={host} snapshot={snapshot} selected={selected} onSelect={setSelected} active={active} /> : <View style={{height:200,alignItems:"center",justifyContent:"center",backgroundColor:C.bg}}><GravityMark size={170} /><Text style={t.faint}>{reduced?"Reduced motion · select an agent below":"No roster has been reported"}</Text></View>}
        <Text style={[t.faint,{marginTop:10,marginBottom:20}]}>Paths show reported delegation. A light packet marks a new recorded action while Core is visible.</Text>
        <View style={{gap:6}}>{agents.map((row,index)=><Pressable key={row.id} accessibilityRole="button" accessibilityLabel={`Inspect ${row.name||row.id}`} accessibilityState={{selected:row.id===selected}} onPress={()=>setSelected(row.id)} style={({pressed})=>({flexDirection:"row",alignItems:"center",gap:14,minHeight:62,padding:14,borderRadius:8,backgroundColor:row.id===selected?C.emberSoft:pressed?C.s3:C.s1,borderLeftWidth:2,borderLeftColor:row.id===selected?C.ember:"transparent"})}><Text style={[t.mono,{fontSize:11,color:row.id===selected?C.ember:C.ink3}]}>{String(index+1).padStart(2,"0")}</Text><View style={{flex:1}}><Text style={[t.body,{fontWeight:"600"}]}>{row.name||row.id}</Text><Text style={t.faint}>{waiting?"Waiting for business generation":label(row.status)}</Text></View><Icon name="arrow-forward-outline" size={18} color={row.id===selected?C.ember:C.ink3} /></Pressable>)}</View>
        {!agents.length && <Empty title="No agents reported" body="Refresh when the supervisor engine is available on your PC." />}
      </Section>
      <Section title="Agent inspection"><Card style={{gap:14}}>{agent?<>
        <Text style={t.h2}>{agent.name||agent.id}</Text><Pill label={waiting?"Waiting for business generation":label(agent.status)} />
        <View><Text style={t.label}>Current task</Text><Text selectable style={[t.body,{marginTop:6}]}>{waiting?"Business generation owns the workstation. Supervisor inference is waiting.":taskText(agent.task)}</Text></View>
        <View><Text style={t.label}>Role instructions</Text><Text selectable style={[t.muted,{marginTop:6}]}>{agent.instructions||"No instructions reported."}</Text></View>
        {!!agent.model && <View><Text style={t.label}>Reported model</Text><Text style={[t.mono,{marginTop:6}]}>{agent.model}</Text></View>}
        {!!latestGoal && <View><Text style={t.label}>Latest delegated goal</Text><Text selectable style={[t.body,{marginTop:6}]}>{latestGoal.goal||"No goal text reported."}</Text><Text style={t.faint}>{time(latestGoal.created_at)}</Text></View>}
        {!!agent.error && <Text style={t.error}>{agent.error}</Text>}
        <Text style={t.label}>This agent's work receipts</Text><Records items={selectedReceipts.slice(-4).reverse()} empty="No tool completion or failure has been recorded for this agent." />
      </>:<Text style={t.muted}>Select an agent from the constellation or roster.</Text>}</Card></Section>
      <Section title="Improvement cycle"><Card style={{gap:14}}>
        <Text style={t.h2}>{job?.goal||job?.title||(job?"Active improvement job":"Give the next cycle a direction")}</Text>
        {job && <Text style={t.muted}>{label(job.stage||job.status)}{job.task?` · ${taskText(job.task)}`:""}</Text>}
        <Field label="Improvement goal · optional" value={goal} onChangeText={setGoal} multiline placeholder="What should Ashvane investigate?" editable={!busy&&!job} />
        <Text style={t.faint}>{!snapshot.enabled?"Enable the master switch before running a cycle.":job?"A job is active. Cancel it before starting another.":blocked?"The reported blocker may prevent work. Starting a cycle asks the PC engine to check.":"The PC runs the investigation and records its evidence here."}</Text>
        <Button label="Run improvement cycle" icon="play-outline" kind="primary" disabled={!snapshot.enabled||!!job||!!busy} busy={busy==="/run"} onPress={()=>act("/run",{goal:goal.trim()},"Improvement cycle requested. Check the reported task and receipts.")} />
        <Button label="Cancel supervisor work" icon="stop-outline" kind="danger" disabled={!job||!!busy} busy={busy==="/cancel"} onPress={()=>act("/cancel",{},"Cancellation requested. The PC is draining owned work.")} />
      </Card></Section>
      <Section title="Recorded work" right={<Pill label={`${receipts.length} receipts`} />}><Card><Text style={[t.faint,{marginBottom:14}]}>Tool completions: {completedTools} · failures: {failedTools}</Text><Records items={receipts.slice(-8).reverse()} empty="No tool completions or failures recorded yet. A running state alone is not completed work." /></Card></Section>
      <Section title="Job history"><Card><Records items={rows(snapshot.jobs).slice(-5).reverse()} empty="No supervisor jobs have been recorded." /></Card></Section>
      <Section title="Evidence ledger"><Card><Records items={rows(snapshot.events).slice(-6).reverse()} empty="No supervisor events have been recorded." /></Card></Section>
      <Text style={t.faint}>Core maintains Ashvane across all four workspaces. Business production and destination accounts remain separate.</Text>
    </>}
  </ScrollView>;
}

function Records({items,empty}) {
  if (!items.length) return <Text style={t.muted}>{empty}</Text>;
  return <View style={{gap:20}}>{items.map((row,index)=><View key={row.id||index} style={index?{paddingTop:20,borderTopWidth:1,borderTopColor:C.line}:null}>
    <Text selectable style={[t.body,{fontWeight:"600"}]}>{row.summary||row.goal||row.title||label(row.kind||row.status)}</Text>
    {!!(row.result||row.error) && <Text selectable style={[t.muted,{marginTop:6},row.error&&{color:C.bad}]}>{typeof (row.error||row.result)==="string"?row.error||row.result:JSON.stringify(row.error||row.result)}</Text>}
    <Text style={[t.faint,{marginTop:6}]}>{row.role?`${label(row.role)} · `:""}{row.kind||row.status?`${label(row.kind||row.status)} · `:""}{time(row.at||row.created_at)}{typeof row.passed==="boolean"?row.passed?" · passed":" · failed":""}</Text>
  </View>)}</View>;
}
