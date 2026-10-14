# Supervisor neural interface decisions

## Decision sheet

SUBJECT — The Ashvane owner needs to see which local supervisor agents are available, which one is actually working, and how evidence, delegation, checks and review move through a shared improvement cycle.

GROUND — The underlying artifacts are a director's delegation tree, source and public research, isolated baseline/candidate checks, an independent reviewer verdict, and a durable event ledger. The visualization borrows the branching geometry of a neural network because the backend really does have one coordinating role, specialist branches and discrete recorded actions. It is an operational diagram, not a claim of simulated cognition.

PALETTE — Deep mineral blue #07121B (cool biased ground); lifted blue #10212D (panel); bone #E7EFEB (primary text); sea glass #A9C0C5 (secondary text); slate #31505D (structural line); amber #FFC27D (director); turquoise #75DDCF (research); orchid #C29BFF (engineering); mint #9EE6B7 (evaluation); coral #FF9B92 (review). Role colors identify actual agents only. Muted structural edges cannot be mistaken for work pulses.

TYPE — Bahnschrift is the restrained display face already used in the installed product; Segoe UI reads the records and controls. Tabular numerals and a compact mono stack carry IDs and timestamps. No display face is used for backend text.

SPACE — 6/12/18px within controls; 28/40px between operating regions. The brain stage owns the width and height. Quiet information panels use smaller type and deliberate whitespace so the visualization has one focal point.

SHAPE — 10px primary surface radius with smaller 6px nested controls. Depth uses tonal steps; only the rendered filaments emit light. Buttons and cards do not receive decorative glows.

MOTION — Three bounded moments: a slow camera drift under 1 degree that establishes volume, a 180ms selection response, and a finite packet moving only when a new event arrives after the baseline snapshot. Reduced motion freezes the view, shows selection instantly, and retains event text. The render loop has a 30fps cap and pauses when hidden or offscreen.

SIGNATURE — A volumetric coordinating hub with role-colored neuronal clusters and curving dendrites. It depicts the actual roster and actual delegation records. Each role has a readable, accessible button outside the canvas.

## Critique and correction

A generic AI dashboard could use a pulsing brain with every branch glowing. That would turn availability into a false claim of activity. The design instead gives available branches a quiet structural appearance; only a newly observed ledger event creates a short traveling packet. The first snapshot establishes history and triggers none. No ambient flicker, fabricated throughput, or pulsing idle agent is permitted. A generic network would connect every node to every other node. This backend starts with the director and records delegated parent/child goals, so those are the only relationships presented as such. A role can exist without a delegation edge.

## Data contract

`snapshot.agents` creates and removes real role clusters. `status` and `task` supply labels and inspector content; `idle` and `waiting_for_business` remain visually calm. `snapshot.goals` supplies recorded parent-to-child delegation links, with their real goal text available in the list. `snapshot.events` supplies packet events after an initial ID baseline; packets are limited to genuinely new IDs with a recent backend timestamp while the stage is visible. A new saved goal animates its actual parent-to-child branch; a `delegate` request event alone does not. Actions such as `research`, `training_example`, and `propose_change` are logged before their tools run, so their event means a recorded request, never proof of completion. `kind`, `role`, `summary`, `passed`, and `candidate_id` remain visible in Activity. The center represents the shared host/supervisor and is clearly labeled, not another AI role. Source, local files, public research, extensions, sandbox checks, and promotion are shown as capability or process annotations only when reported by the snapshot. The evaluator role is distinct from the deterministic Sandbox checks. The reviewer is asked after baseline and candidate evaluations even when they fail. Source promotion requires measured improvement, a passing reviewer verdict, `auto_apply`, and an enabled master switch; the graphic does not imply automatic application. The master switch, run/cancel, jobs/rollback, goal tree and dataset export retain their existing API paths and controls.

## Resilience and accessible equivalent

WebGL failure or context loss leaves the real roster buttons, status, task, event and goal lists usable. Pointer selection on a 3D node mirrors the roster selection; the canvas is excluded from assistive technology because the buttons are its complete keyboard equivalent. The module owns its renderer and all listeners and disposes geometries, materials and animation on teardown. ResizeObserver resizes the bounded renderer. Device pixel ratio is capped at 1.5, rendering is capped at 30fps, and IntersectionObserver plus Page Visibility pause it. Reduced motion disables camera drift and packet travel while still showing the new event in Activity. No visual QA claim is made without an actual browser rendering inspection.

## Dependency

The local Three.js ESM build is pinned to npm `three@0.186.1`, MIT, at `static/vendor/three/0.186.1/`. Registry package integrity, verified against the downloaded archive: `sha512-blFeqb49wRCSGUGj7gtpfnSGHy2lwDk94RhUmS1c/hTby70kvChbWpkJ4Pm1390LqzzvTmzgXKHPEafJwCb8jA==`. SHA-256 of `build/three.module.js`: `9052042D676CB0FDC1DDFEFE193053F34B7AC0513A616FDAC4535D49987812EA`; of `build/three.core.js`: `9EDDE002B066A9A05676A6127F67735B62BAF399BDEA529F2F7E31657DA769E6`. Runtime does not fetch a CDN.

Primary API references: [WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer.html),
[BufferGeometry](https://threejs.org/docs/pages/BufferGeometry.html),
[MDN WebGL best practices](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices).
Each API description comes from its maintainer, a single primary origin. This is an implementation
choice rather than a comparative claim about the best available graphics library.

## Installation and verification

Installed the controller, scene, topology, styles and pinned library in the current Windows
package. Verified SHA-256 equality between source, installed files and every served asset on
the actual port 8787 dashboard. The old desktop hub had finished its pipeline shutdown but kept
its process alive without a dashboard listener; restarted that exact hub after confirming no
capture helpers were running. Saved business enablement preferences were preserved.

The full source suite passed: 984 tests, five skips. Isolated frozen-package startup, authenticated
APIs, independent business switches and static-file checks passed. Node checks cover real-record
mapping, no initial-history playback, duplicate/late event handling, task selection, waiting-state
honesty, portrait framing, visibility, context loss/recovery, reduced motion and resource disposal.
Scene checks instantiate real Three.js geometry with a stub renderer; they do not establish
pixel appearance or actual graphics-driver performance. No browser/desktop UI automation was used.
The static interface checker reported no errors or warnings; its four advisory results matched
CSS `100%` dimensions, not made-up statistics. Module fingerprints propagate from topology to
scene to controller and HTML, preventing stale nested imports after an update.

Production audit before this installation found one deferred job, zero generated examples, zero
saved goals and zero research sources. Core has these capabilities, but had been waiting for
Surge to release workstation resources. Do not present that ledger as evidence of already completed
autonomous improvements or model weight training.
