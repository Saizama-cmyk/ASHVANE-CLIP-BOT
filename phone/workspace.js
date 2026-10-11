import { useCallback, useEffect, useRef, useState } from "react";
import { call } from "./api";

export function useWorkspace({ host, token, onUnauthorized }, prefix) {
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const live = useRef(true), controllers = useRef(new Set());
  useEffect(() => { live.current = true; return () => { live.current = false; controllers.current.forEach(c => c.abort()); }; }, [host, token]);
  const request = useCallback(async (path, options = {}) => {
    const controller = new AbortController(); controllers.current.add(controller);
    try {
      const r = await call(host, prefix + path, { token, timeout: 65000, ...options, signal: controller.signal });
      if (r.status === 401) onUnauthorized?.(true);
      if (!r.ok || r.data?.ok === false) throw new Error(typeof r.data?.detail === "string" ? r.data.detail : r.data?.error || `The PC answered ${r.status}. Try again.`);
      return r.data;
    } finally { controllers.current.delete(controller); }
  }, [host, token, prefix, onUnauthorized]);
  const action = async (run, message) => {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try { await run(); if (live.current) setNotice(message || "Saved on your PC."); }
    catch (e) { if (live.current && e.name !== "AbortError") setError(e.message || "The PC could not complete this operation."); }
    finally { if (live.current) setBusy(false); }
  };
  return { request, error, setError, busy, notice, action };
}
