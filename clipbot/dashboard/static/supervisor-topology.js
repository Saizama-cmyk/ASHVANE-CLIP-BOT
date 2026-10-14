/* Pure mapping from supervisor records to visible topology and event activity. */
export function roleEdges(goals, roleIds) {
  const ids = new Set(roleIds.map(String));
  const seen = new Set();
  const edges = [];
  for (const goal of Array.isArray(goals) ? goals : []) {
    const parent = String(goal?.parent || ''), child = String(goal?.agent || '');
    const key = `${parent}>${child}`;
    if (!ids.has(parent) || !ids.has(child) || parent === child || seen.has(key)) continue;
    seen.add(key);
    edges.push({parent, child});
  }
  return edges;
}

export function rolesOperational(snapshot) {
  return snapshot?.enabled === true && ['investigating', 'evaluating', 'applying'].includes(snapshot.state);
}

export function nextEventPackets(previous, events, {baseline = false, visible = false, now = Date.now() / 1000} = {}) {
  const seen = new Set();
  const fresh = [];
  for (const event of Array.isArray(events) ? events : []) {
    if (typeof event?.id !== 'string' || !event.id) continue;
    seen.add(event.id);
    if (!baseline || !visible || previous.has(event.id)) continue;
    if (typeof event.role !== 'string' || typeof event.kind !== 'string') continue;
    if (typeof event.at !== 'number' || !Number.isFinite(event.at) || now - event.at < 0 || now - event.at > 20) continue;
    fresh.push(event);
  }
  return {seen, fresh};
}

export function nextDelegations(previous, goals, {baseline = false, visible = false, now = Date.now() / 1000} = {}) {
  const seen = new Set();
  const fresh = [];
  for (const goal of Array.isArray(goals) ? goals : []) {
    if (typeof goal?.id !== 'string' || !goal.id) continue;
    seen.add(goal.id);
    if (!baseline || !visible || previous.has(goal.id)) continue;
    if (typeof goal.parent !== 'string' || typeof goal.agent !== 'string') continue;
    if (typeof goal.created_at !== 'number' || !Number.isFinite(goal.created_at) || now - goal.created_at < 0 || now - goal.created_at > 20) continue;
    fresh.push(goal);
  }
  return {seen, fresh};
}
