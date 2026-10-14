/** Read reported admission limits without inventing capacity for absent fields. */
export function resourceSummary(budget) {
  if (!budget) return "";
  const parts=[],creative=budget.creative,pipeline=budget.pipeline;
  if (Number.isFinite(creative?.pending) && Number.isFinite(creative?.limit)) parts.push(`${creative.pending}/${creative.limit} creative requests`);
  if (creative?.waiting_reason) parts.push(String(creative.waiting_reason).replace(/_/g," "));
  const waits=[pipeline?.assembly,pipeline?.ai,pipeline?.edit].map(stage=>stage?.waiting).filter(Number.isFinite);
  if (waits.some(value=>value>0)) parts.push(`${waits.reduce((sum,value)=>sum+value,0)} waiting for processing slots`);
  if (pipeline?.shared_gpu?.waiting_reason) parts.push(String(pipeline.shared_gpu.waiting_reason).replace(/_/g," "));
  if (budget.production?.active) parts.push("Production active");
  return parts.join(" · ");
}
