# Supervisor interface decisions

Subject: Ashvane's owner needs one place to enable, stop, inspect and direct the improvement agents shared by Surge, Hollow, Resonance and Social Studio.

Ground: an operations observatory. A perspective orbital grid locates the real agents around their shared coordinator. Connections express membership in the supervisor, not invented inter-agent traffic.

Palette: void #070A10 is the blue-biased neutral; hull #111925 separates instruments; text #DFE8ED carries decisions; telemetry #98A9BA carries context; rails #304353 give the network structure; accretion amber #DAA66B identifies the shared master control. Status is always written alongside color.

Type: Bahnschrift headings match the existing physical instrument shell. Segoe UI remains the reading and utility face. Tabular numerals make counts and timestamps comparable. No decorative type for operational data.

Space: 8/12 pixels within controls; 24/36 between operational areas. The network receives the primary region, with inspection immediately beside it rather than in a distant modal.

Shape: 8-pixel corners; tonal elevations only. Orbital circles belong to the network illustration; ordinary cards remain rectangular.

Motion: two short moments, 120–180 ms, for control press feedback and agent selection. No simulated scanning, pulses, spinning planets or fake traffic. Reduced motion keeps opacity and focus feedback without spatial travel.

Signature: the real agent constellation, with selectable instrument plates above a tilted orbital plane. The master switch remains visible outside the page, across all four businesses.

Critique: a generic infrastructure page would use KPI cards and decorative animated nodes. This design instead starts with the owner's stop control and current agent tasks. The orbital visual exists to inspect actual agents, carries no fabricated activity, and becomes a normal button list on phones. Supervisor is shared infrastructure, never a fifth business or account profile. Backend acknowledgement owns the persistent switch; failed requests retain the last confirmed value and expose an error.

States: initial unknown state disables mutations; loading and request failures are explicit; an empty roster, events, jobs, goals or dataset has its own explanation. Disabling immediately requests backend cancellation/draining and waits for confirmed state. Active work can be cancelled without turning off future runs. Rollback is offered only for jobs explicitly reported eligible by the server.

Validation: JavaScript syntax and all inline scripts pass. HTML parsing confirms 454 unique static IDs, 19 Supervisor references resolve, and the picker still has exactly four businesses. Code unit checks with a mocked DOM/API confirm reported counts, events, capabilities, rollback candidate IDs, run/cancel, acknowledged master state and protection from a stale GET overwriting a mutation. Shared navigation preserves the current business and reopens its settings. The skill checker reports only an advisory false positive for a CSS 100% axis, not fabricated statistics. UI automation is prohibited by the current user instruction, so no browser automation is used.
# Runtime evidence addition, 13 October

Use the existing Core panel typography, colors, spacing and responsive columns. Add a
Runtime observations panel beside the work controls: recent fault counts and source
locations, aggregate wait age and sampled GPU usage. No new animated ornament, business
switch or interaction. Empty means no faults observed during this process/window;
missing measurements show unavailable, never zero. Master-off states collection stopped;
busy states inference waiting, while cheap metadata collection remains live. Fault text
is fixed source identifiers and counts, not raw private log content. Keyboard and small
screen behavior use the existing panel and records styles. API failure uses the existing
notice and retry/refresh controls.

