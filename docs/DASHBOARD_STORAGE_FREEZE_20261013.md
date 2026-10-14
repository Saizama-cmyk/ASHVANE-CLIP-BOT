# Dashboard freeze during live capture

The installed neural interface initially served correctly, including all pinned module bytes.
Later public dashboard requests timed out while Surge processed clips. A nonblocking py-spy
0.4.2 stack inspection of the actual desktop hub showed its `engine` thread inside
`assembler.assemble -> Path.mkdir` on capture work storage. A second snapshot showed
`assembler.assemble -> concat_list -> Path.resolve -> ntpath.realpath`. These are synchronous
disk operations on the same asyncio loop that serves the dashboard. Worker threads were
concurrently blocked in buffer stat, prune and cleanup calls. This establishes the observed
blocking call sites; it does not establish a physical drive fault.

The assembly fix moves work-folder creation, segment existence checks, concat-path resolution
and writing, output existence checks and cleanup off the engine loop. ffmpeg executable
discovery is also performed in a worker thread. Existing cut planning, encoding parameters,
quality thresholds, scheduling, publication and saved business flags are unchanged.

Regression tests instrument filesystem calls and fail if they run on the engine thread.
They failed against the original implementation at the same mkdir call, then passed with the
fix for successful cuts, command failures and cancellation. The existing real ffmpeg cut and
quality-check tests passed as well: nine assembler tests total.

The profile tool is a temporary development dependency under artifacts/debug-tools, not a
business dependency or cloud service. It reads call stacks without local-variable capture.
See [py-spy's own documentation](https://github.com/benfred/py-spy#dump) for the tool's dump mode.
The recorded second stack is in artifacts/dashboard-freeze-stack.json.

Repeated Kick Pusher cluster errors are a separate remaining backlog item. Other synchronous
storage operations elsewhere in the suite may also need profiling; this patch is not a claim
that every runtime latency issue is solved.

Full suite after the fix: 987 passed, five skipped. The owner-authorized source update is
staged through the existing pinned runtime loader; artifacts/assembler-storage-update.json
records its exact hash and activation version. It takes effect on the next launch, not in
the current Python process. The owner has been asked to quit the running app from its tray
before restart because active captures are running and desktop actions are reserved to the
owner. Live post-restart verification remains pending that action. This manual maintenance
update is not an autonomous supervisor success or a generated training example.

A future normal package build that includes this patch should fold in/remove this owner
overlay so it does not shadow later package changes to assembler.py.

Follow-up: the owner explicitly authorized closing and reopening the app. Restarted the exact
desktop hub and its owned process tree, then launched the current installed executable normally.
The expected overlay version is active and its boot marker cleared, confirming readiness.
The live server returned the updated dashboard and all four switches. Some subsequent requests
still timed out. A fresh nonblocking stack found another synchronous storage path:
`pipeline.snapshot -> capture.snapshot -> capture.segments -> list_segments -> Path.stat`.
That separate live-status bottleneck remains open; the assembler patch is active. See
artifacts/assembler-storage-restart.json and artifacts/post-restart-stack.json.

13 October follow-up complete: capture.snapshot now reads only immutable observations
published by existing worker scans. It reports availability, observation time/age and
scan error separately; it never enumerates or stats capture storage. Regression coverage
holds the scanner blocked while status remains responsive, then forbids all scanner
calls during cached snapshots. The normal Windows package includes both fixes, and
the temporary owner overlay has been retired without deleting its recoverable files.
All 1,002 tests passed, five skipped. Frozen API/profile/switch checks passed. Reopened
normally; eleven post-startup shell requests returned 200 in 0.015–1.266 s while
capture helpers resumed. Evidence: artifacts/reliability-restart-20261013.json.
This validates the observed call sites and short restart sample, not indefinite uptime.
Kick transport remediation is documented separately in KICK_REALTIME_20261013.md.
