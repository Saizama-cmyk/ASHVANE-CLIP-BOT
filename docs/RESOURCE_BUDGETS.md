# Actual resource budgets and visible generation queues

The four manual business switches keep their existing persisted enablement and
stop behavior. These changes expose and bound work inside those businesses;
they do not add another scheduling controller or start a stopped business.

## Existing worker limits

Surge assembly, AI and edit workers keep `workers.pipelines`, `workers.ai_stage`
and `workers.editors`. Their shared `Limiter` now records the number of coroutines
actually waiting for capacity, in addition to active reservations and the current
limit. Cancellation removes a waiter; cancellation during release still returns
its occupied slot. Lowering a limit lets existing reservations finish and keeps
new work waiting until capacity is available. No work estimate is presented as an
observed count.

Clip phase records retain their measured timestamps and durations. Active
`assemble_wait`, `ai_wait`, `edit_wait` and `transcribe_wait` phases now carry fixed
waiting reasons. Recent completed records have no current waiting reason. The
original latency `*_slots` shape stays compatible; `worker_queues` adds the richer
measured counters.

The pipeline's existing candidate backpressure policy remains intact. Its
`backlog.capacity` is a pressure denominator, **not a newly enforced hard queue
cap**, so the new snapshot calls it `pressure_capacity` and explicitly identifies
the policy as `backpressure`. Candidate lifetime deadlines and the worker limits
continue to bound processing. Transcription exposes active work and actual
`transcribe_wait` phase counts; its `configured_limit` is explicitly configuration
because changing transcriber capacity requires the existing restart behavior.

## Bounded creative admission

`creative.max_pending_per_business` limits the total accepted active, preparing,
waiting and finishing requests for each business. The default is four, configurable
from one through 32. The admission check and reservation contain no await, so
concurrent HTTP handlers cannot both reserve the final slot. A full queue returns
HTTP 429 before adding a task or constructing a local inference request. Retrying
requires the owner to wait or cancel current work; no unbounded retry queue exists.

Story ideas, lyrics, reference-derived creative requests and Social ideas use
`CreativeTools.chat`. Social's draft path now takes the **same** admission budget,
including drafts that previously queued directly on the GPU lock. Ideas and drafts
therefore share the per-business count. Nested admission within one request holds
one reservation. A failure during preparation, model request or postprocessing
releases the reservation, as does cancellation. Stopping one business cancels its
accepted tasks while leaving other businesses' tasks alone.

CreativeTools and Social drafts use the pipeline's existing shared GPU lock, then
the story team's existing lock when that is the available integration, with one
shared service lock as the fallback. Queue state distinguishes actual preparation,
waiting on that lock, local inference and finishing. The fallback also serializes
inference when a full pipeline has not been attached.

Hollow's production studio and Resonance's producer already reject a second active
production job. Their existing one-job limits are reused and reported, without
introducing queues or replacing their business controls. Creative ideas/lyrics
are a separate admission budget from those production jobs.

## Snapshot contract

`Pipeline.snapshot.resource_budget` contains:

```text
assembly / ai / edit: {active, waiting, limit, available}
transcription: {active, waiting, configured_limit}
shared_gpu: {locked, waiting, waiting_reason}
phases: {phase_name: active_record_count}
candidate_queue: {active, pressure_capacity, policy: "backpressure"}
```

Shared GPU `waiting` counts live queued futures on the known stdlib asyncio lock.
For an unknown lock implementation it is unavailable (`null`), not an estimated
zero. This is a global queue count; it is not attributed to particular businesses
or clip phases without separate evidence. A locked GPU alone does not establish
which business owns it.

`GET /api/businesses` adds top-level `resource_budget`:

```text
pipeline: the pipeline budget above, or null when unavailable
creative: {clips, stories, music, social}
story_production / music_production: {limit: 1, active, queue_policy: "reject_while_active"}
```

Each creative row contains `pending`, `limit`, `active`, `waiting`, `preparing`,
`finishing`, `waiting_reason` and `admission_full`. Pending is the total accepted
request count; active counts requests in local inference. The reason is
`shared_gpu_busy` only when an accepted request is actually waiting on that lock.
Each business row also includes its corresponding `resource_budget` with creative
and applicable pipeline/production data. Snapshots expose counts and fixed reasons,
not task identifiers, client names, prompts, saved media or source paths. Snapshot
collection performs no new file scans, database reads, network calls or inference.

## Verification

Focused regression coverage exercises exact waiter counts, waiter cancellation,
runtime downsizing, cancellation during slot release, live GPU waiters, per-phase
reasons, rejection before HTTP dispatch, shared Social draft/idea admission,
cross-business cancellation isolation, preparation failure, nested reservation
cleanup and existing single-production limits. Local model HTTP is mocked; no
production model request or generation was run for this change.

Focused verification passed **163 tests in 12.08 seconds**:

```text
.venv\Scripts\python.exe -m pytest -q tests/test_resource_budgets.py tests/test_latency.py tests/test_creative.py tests/test_social.py tests/test_business_runtime.py tests/test_supervisor_observations.py tests/test_no_hardcoded.py
```

This is not a full-suite or installed-runtime claim. Dashboard and phone rendering
use this contract and remain the parent task's implementation responsibility.
