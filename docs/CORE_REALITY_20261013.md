# Core capability and outcome audit — 13 October 2026

Core has executable local agent, public research, source-edit staging, isolated
regression evaluation, reviewer, promotion and rollback implementations. Its
production ledger did **not** establish completed autonomous improvements at the
time of this audit. At 22:08 UTC the real ledger contained one deferred job, zero
public sources, zero delegated goals, zero examples and zero learning outcomes.
The initial event inventory was five entries: four stops and one deferral. These
are actual aggregate counts; no private production messages or identifiers were
copied into this report.

A later installed-production count-only ledger read on 13 October recorded **11
events, two tool receipts, two jobs and four public sources**. It contained **zero
production examples and zero `source_applied` changes**. This supersedes the early
empty-receipt snapshot as a description of current ledger activity, without
retrospectively changing the earlier observation. Actual receipts establish that
operations returned; they do not establish a completed production repair. The
separate disposable UUID trial and its one eligible example remain test evidence,
not production outcomes.

The supported production settings selected Core enabled, idle-only inference,
30-minute cycles, eight shared agent turns, Qwen3-VL 8B Instruct decisions and
Qwen3-Coder 30B engineering. Automatic promotion and idle activation were enabled.
The configured source checkout existed. The loopback model service initially
returned ConnectError. After the parent task started the existing installed
Ollama executable, inventory succeeded and both configured models were present
among four installed models. A read-only Docker readiness check succeeded with
engine 29.6.1 and the trusted local evaluation image. This is current readiness,
not proof that an evaluation or production repair completed.

The busy guard was inspected against the pipeline implementation: `_inflight`
holds clip candidate processing tasks, not capture watchers. Continuous capture
alone does not block Core. Active clip generation, story/research/social work,
creative jobs, the resident music engine or another shared GPU owner can defer
inference. The priority policy remains intact.

## Implemented repairs

- Capability inventory survives unavailable/malformed/oversized Ollama inventory
  responses and still reports the source checkout and isolation readiness. Model
  inventory now streams under the existing byte ceiling. Error metadata records
  exception type without persisting service diagnostic text.
- Missing engineering weights no longer prevent decision-only investigations.
  Engineering remains blocked without its configured installed model. Separate
  `inference_ready` and `repair_ready` describe distinct prerequisites.
- Fixed, non-private blocking codes identify real business ownership, the master
  switch and unavailable/missing decision inference. Waiting age and the next
  scheduled check are exposed, without inventing throughput or progress.
- While inference waits for businesses, the scheduler can fetch only configured
  public research feeds through the existing bounded public fetcher. It saves
  real URL/hash/time provenance and records partial/failed fetches. The next
  director receives recent provenance alongside observed runtime faults. This
  performs no local inference or candidate execution.
- Tool requests and actual tool returns are now distinct durable records, linked
  by request ID and investigation ID where applicable. Compact receipts expose
  actual source counts, quarantine/eligibility, proposal status and measured
  checks/review. They exclude raw file content, tool outputs and fabricated
  success claims. Extension error results are failures even without an exception.
- Exhausting the shared budget records `budget_exhausted`, rather than presenting
  that condition as a completed investigation. Invalid delegation cannot leave a
  phantom saved goal.
- Inference rechecks the master switch and business ownership after acquiring
  the shared GPU lock, closing a contention race without spending a deferred
  turn. Core's own lock ownership is not reported as business generation.
- Enabling Core requests the existing application dependency manager; launch,
  reuse and process ownership stay with that manager. The parent task owns its
  Core-only startup eligibility and settings help update.

## Snapshot additions

`blocking_reason` is null or `{code, reason, details}`. `details` contains only
fixed cause identifiers such as `clip_generation_active`, `music_engine_resident`
or `shared_gpu_owned`. `blocking_since` is a timestamp for the current business
wait, and `next_cycle_at` is the scheduler's planned next check when known.

Capabilities add `model_inventory: {available, checked_at, error_type?}`,
`decision_model_available`, `engineering_model_available`, `inference_ready` and
`repair_ready`. Before inventory runs, the capabilities object remains unverified;
absence must render as unknown, not unavailable or ready.

`work_receipts` contains actual `tool_completed`/`tool_failed` ledger events,
with `action`, `request_id`, optional `job_id`, and `outcome`. Outcomes distinguish
completed, partial, failed and interrupted operations. Operation completion is
not proof of a code improvement: use `status`, `checks_passed`, `review_passed`
and the existing source promotion journal. Training example receipts explicitly
report `eligible`/`verified`; agent-generated untested answers remain quarantined.
Existing action events now have `phase: requested`. Historic request events
without receipts are not retrospective evidence of completed tools.

## Verification and limits

The focused command was:

```text
.venv\Scripts\python.exe -m pytest -q tests/test_supervisor_reality.py tests/test_supervisor.py tests/test_supervisor_memory.py tests/test_supervisor_observations.py tests/test_supervisor_sandbox.py tests/test_supervisor_changes.py tests/test_no_hardcoded.py
```

Result: **209 passed, one skipped in 25.13 seconds**. The skip is the existing
Windows link-privilege negative control. Tests use local doubles for inference,
network and Docker, and temporary source workspaces for staging/promotion/rollback.
Negative controls cover unavailable inference, missing engineer models, actual
generation versus capture watching, private identifiers, requested versus returned
tools, quarantined examples, phantom delegation, master/GPU races and non-inference
public preparation. Existing protected baseline, candidate, review and rollback
checks were included. No full-suite claim is made by this audit.

This subtask did not build, install or restart Ashvane, run production inference,
execute a production candidate, install extensions, grant sandbox networking or
change privacy boundaries. A completed real production cycle must be reported
separately after installation from its actual receipts. Code capability and passing
mocked boundary tests are not substitutes for that evidence.

Core still produces datasets and outcome memory, not model-weight training. It
has no consciousness or self-awareness implementation. Unknown reuse rights and
untested synthetic responses stay excluded from training exports. Autonomous
source promotion still requires real isolated baseline/candidate evidence, an
independent reviewer, current source hashes, enabled auto-apply and the enabled
master switch. Docker or source unavailability holds repairs; it never causes
candidate execution on the host.

## Deferred-work scheduling repair

The normal cycle interval previously also controlled retries after business
contention. A business finishing just after a check could therefore leave Core
waiting almost the full 30 minutes. `supervisor.idle_recheck_s` now controls cheap
resource checks independently (15 seconds by default, configurable from one to
120 seconds). These checks perform no inference. Public feed preparation remains
limited to once per normal cycle interval while waiting, rather than repeating
at every resource check. One owned public preparation task runs independently,
so a slow source fetch cannot hold the idle recheck loop. Cancel and master-off
drain that task as well as the investigation.

A deferred owner investigation resumes the same recorded job when resources are
available. It keeps its remaining shared turn budget and receives the job's real
prior tool receipts; deferrals do not replenish model turns. A completed,
budget-exhausted, failed or cancelled cycle waits the normal interval before a
new autonomous cycle. Explicit cancellation clears any deferred resume, and
master-off still stops the scheduler. A new explicit owner request can supersede
an older deferred request without running both.

`next_cycle_at` is unknown while work is active or awaiting business resources.
It is a future timestamp only while waiting for the normal cycle interval; it
is not an estimate of when business generation will finish. Deterministic
clock/controller regressions cover busy-to-idle pickup, normal interval spacing,
throttled public preparation, same-job/budget resume, and both active and deferred
cancellation. Production inference was not used to test this repair.

The scheduler/controller/no-hardcoded gate passed **133 tests in 31.17 seconds**.
An additional cancellation/master-off/slow-source selection after the final
cancellation ordering adjustment passed **five tests in 4.44 seconds**. These are focused
source checks, not an installed production cycle or full-suite claim.
