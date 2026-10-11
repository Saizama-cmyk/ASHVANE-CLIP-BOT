export function releaseVersion(release) {
  for (const label of [release?.tag_name, release?.name]) {
    const found = String(label || "").match(/\d+\.\d+\.\d+/);
    if (found) return found[0];
  }
  return "";
}

export function isNewerVersion(latest, current) {
  const parse = value => /^\d+\.\d+\.\d+$/.test(String(value || ""))
    ? String(value).split(".").map(Number) : null;
  const next = parse(latest), installed = parse(current);
  if (!next || !installed) return false;
  for (let index = 0; index < next.length; index += 1) {
    if (next[index] !== installed[index]) return next[index] > installed[index];
  }
  return false;
}
