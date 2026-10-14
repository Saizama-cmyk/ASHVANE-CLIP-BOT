/** The renderer receives topology and timestamps only: never tasks, credentials or tokens. */
const list = value => Array.isArray(value) ? value : [];
const id = value => typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value) ? value : "";
const text = value => typeof value === "string" ? value.slice(0, 160) : "";
const stamp = value => typeof value === "number" && Number.isFinite(value) ? value : null;
const receipt = row => id(row?.id) && id(row?.role) && ["tool_completed", "tool_failed"].includes(row?.kind) && stamp(row?.at) !== null;
export function sceneSnapshot(value) {
  return {
    enabled: value?.enabled === true, state: text(value?.state),
    agents: list(value?.agents).slice(0, 48).map(row => ({id: id(row?.id), name: text(row?.name), status: text(row?.status)})).filter(row => row.id),
    events: list(value?.events).slice(-128).map(row => ({id: id(row?.id), role: id(row?.role), kind: text(row?.kind), at: stamp(row?.at)})).filter(row => row.id),
    work_receipts: list(value?.work_receipts).slice(-128).filter(receipt).map(row => ({id: row.id, role: row.role, kind: row.kind, at: row.at})),
    goals: list(value?.goals).slice(-128).map(row => ({id: id(row?.id), parent: id(row?.parent), agent: id(row?.agent), created_at: stamp(row?.created_at)})).filter(row => row.id),
  };
}
export function sceneMessage(snapshot, selected, active = true) {
  return {type: "ashvane-core-snapshot", snapshot: sceneSnapshot(snapshot), selected: id(selected), active: active === true};
}
export function safeSceneJSON(value) {
  return JSON.stringify(value).replace(/</g, "\\u003c").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

export function acceptSceneMessage(raw, snapshot) {
  if (typeof raw !== "string" || raw.length > 1024) return null;
  try {
    const message = JSON.parse(raw);
    if (message.type === "ashvane-core-select" && id(message.id) && list(snapshot?.agents).some(row => row.id === message.id)) return {id: message.id};
    if (message.type === "ashvane-core-status" && ["ready", "paused", "unavailable"].includes(message.status)) return {status: message.status};
  } catch { return null; }
  return null;
}
