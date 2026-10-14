# Ashvane Core

Core is shared infrastructure for the existing four businesses. It is not another
business or account. Its persistent master switch lives below the business navigation.
Off saves the disabled preference first, stops the scheduler, cancels agents, drains
an atomic source commit if one has already started, and removes only its own tools
and evaluation containers. A restart retains the saved choice.

The local director starts with a verified capability inventory and chooses useful
Ashvane investigations. It can research public sources, discover tools, create saved
specialist roles, delegate work, browse local drives, read bounded local text, propose
source changes, and produce training examples. All agents share a turn budget and
the business GPU lock. Maintenance defers while business generation owns resources;
Yue2's running engine also reserves the workstation. No hosted inference is used.

Installed model selection: Qwen3-VL 8B Instruct for decisions/review and Qwen3-Coder
30B A3B for engineering. The engineering model is sparse but its installed weights
are large, so it is loaded only for its turn. Initial three-case decision benchmarks
exposed mistakes and are not evidence of general reliability. Stronger action schemas
and concrete execution checks are essential. See artifacts/supervisor-model-benchmark*.json.

## Files and changes

Local file discovery supports absolute local drives, bounded searches and text reads.
Credential/account stores, private Ashvane runtime data, environment files, browser
profiles, linked paths and hardlink aliases are excluded. It cannot write arbitrary
files through this browser. Ashvane edits use its configured source checkout.

The engineer stages a small patch with the current source hashes and an executable
reproduction test. Docker runs without a network, private host mounts, credentials or
the Docker socket, as an unprivileged user on a read-only filesystem. Existing tests
and their configuration are immutable. Added reproduction tests run in a separate
subprocess after the original suite succeeds. Promotion requires a passing original
suite, a failing original reproduction assertion, and passing candidate phases, plus
a fresh reviewer verdict over the actual patch. Missing isolation or weak evidence
holds the change. A model cannot declare tests passed through a tool argument.

Promotion writes source atomically and stages a hash-pinned cumulative runtime
overlay. The protected startup loader activates only listed modules/assets; it never
adds an arbitrary folder to sys.path. When enabled, activation restarts Ashvane after
business work drains. Startup readiness confirms the overlay. An unconfirmed or
tampered boot restores the previous overlay on the next launch. Rollback checks for
subsequent owner edits before restoring source. Internal media helper processes use
the bundled implementation; changing those helpers requires a normal package rebuild.
Native dependencies also require a normal package update.

The loader, private account boundaries, file browser, isolated tool/evaluation gates
and redaction boundary cannot be autonomously replaced. Core's own decision loop,
agent workflows and other eligible application source can be improved through the
same repair process. Tests and review reduce risk; they do not prove arbitrary code
is harmless or guarantee that every future defect will be detected.

## Tools and learning

Public Python MCP packages can be acquired from verified pinned PyPI wheels,
installed in a container image, initialized, inspected and invoked in fresh offline
containers with no host mounts. npm is explicitly unsupported. Skills are stored as
untrusted knowledge, not permission grants. Account connectors needing login remain
unconnected until that login exists. See SUPERVISOR_EXTENSIONS.md.

Core records goals, tools, findings, failures, reviews and actual checks. It creates
original synthetic examples and verified repair examples. Every example keeps
provenance and an eligibility flag. Unknown reuse rights or untested answers remain
quarantined. Deterministic held-out cases never enter training exports. Secrets are
redacted before persistence/export. These are JSONL datasets and outcome memory;
there is no implemented model-weight training and no claim of consciousness or
autonomous increases in underlying model intelligence.

## Verification and research origins

On 13 October 2026, the final Windows source suite passed 984 tests, with five skipped.
The complete isolated Docker baseline passed 982 tests, with seven platform/privilege
skips and no failures. The rebuilt executable passed authenticated API/static checks,
its master-off check, actual frozen Python/static overlay activation and boot-health
acknowledgement, and the frozen local neural narration worker. Evidence lives in
artifacts/final-suite-20261013.log, artifacts/supervisor-isolated-baseline.json and
artifacts/packaged-smoke-report.json. The installed source target is
artifacts/windows-revamp/Ashvane/Ashvane.exe; existing shortcuts point there.

The owner's supervisor switch is enabled. The existing business choices are
preserved: Surge enabled, the other three disabled. The idle-only policy defers
maintenance inference during business generation. The rebuilt app was started
minimized and its dashboard readiness was verified.

A disposable real local-model trial reproduced a UUID formatting bug, generated a
correct patch with Qwen3-Coder, passed independent Qwen3-VL review, passed Docker
regressions and staged a runtime overlay. This trial did not edit production source.
Evidence: artifacts/supervisor-local-repair.json. Actual tool installation and offline
MCP invocation were also exercised; see the extension report.

Primary sources used:

- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs
- Ollama tool loop: https://docs.ollama.com/capabilities/tool-calling
- Engineering model card: https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct
- MCP trust/security guidance: https://modelcontextprotocol.io/docs/draft/tutorials/security/security_best_practices

Inference from these sources: schema-constrained JSON is useful for validating shape,
but semantic correctness still needs independent execution evidence. Model selection
here is also based on local measurements, not merely the vendor model card.
