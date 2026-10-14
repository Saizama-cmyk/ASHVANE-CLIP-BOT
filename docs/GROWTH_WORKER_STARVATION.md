# Growth loading during capture storage pressure

The owner reported Growth stuck on Account changed / Loading this profile after Google
reconnection. A nonblocking py-spy snapshot of the installed hub showed all 32 default
asyncio workers occupied by capture segment scans, prune/unlink and buffer cleanup.
Growth and authentication database reads use that same general pool. The engine thread
was idle in its event loop, so this differs from the earlier synchronous snapshot freeze.
Evidence: artifacts/growth-loading-stack.json. This identifies blocked operations, not
a physical drive diagnosis. User logs on the capture drive were slow to read as well.

CaptureManager now owns a configurable bounded storage executor, distinct from general
workers. Capture startup cleanup, scans, pruning, retired buffers and sweeping use it.
Cancellation keeps a running filesystem call's slot occupied until completion. Worker
active/waiting/limit are real observations exposed in Growth. Directory enumeration now
uses scandir entry metadata instead of one additional Path.stat per segment, which avoids
extra Windows metadata queries. Captures remain under their independent Surge switch.

Growth receives configured browser deadlines via a non-secret in-memory runtime script;
timeouts display a retry state. A real profile change invalidates/aborts old reads.
Same-profile account refreshes preserve the loaded dashboard. A controlled controller
test covers reconnect during loading, repeated same-profile events, deadlines and recovery.
The storage regression blocks 40 capture operations and verifies that general metadata
work completes while only two dedicated workers run. It also checks cancellation and
exception slot accounting. Runtime installation/verification is recorded in the task log.
