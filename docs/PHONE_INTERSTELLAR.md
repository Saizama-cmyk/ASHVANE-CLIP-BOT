# Ashvane phone: the living observatory

Decision sheet, 13 October 2026. Extends [the shared design](INTERSTELLAR_DESIGN.md).

**Subject.** The owner's handheld instrument for four independent media businesses and
inspectable local supervisor work. Existing production, account and editing flows stay native.

**Ground.** Photon ring, signal path, agent roster, task evidence, production records. Core
is shared maintenance; entering it does not start a business or a supervisor cycle.

**Palette.** Blue-biased vacuum `#05070D`, hull `#0E1523`, titanium `#273449`, stellar ink
`#F0F4FA`, telemetry `#9FADC2`, ion amber `#F1BC7A`. Fresh evidence uses `#79DCCA` and
faults `#FF8E88`. Restrained per-business color is an identification signal, not a new theme.

**Type.** Space Grotesk for identity and navigation, IBM Plex Sans for reading and form
labels, Plex Mono for measurements where bundled. System fallback while fonts load.

**Space.** Component intervals 6/10/14/20; region intervals 28/40/64. Phone screens remain
single-column, with horizontal navigation scrolling when needed. Controls keep 44px targets.

**Shape.** 14px primary panels, 8px small controls. Tonal separation, no repeated card shadows.

**Motion.** One bounded launch reveal, one business-crossing portal, one visible Core scene.
Reduced motion means immediate navigation and a static Core roster. Backgrounding stops work
polling and removes the scene. No fabricated completion pulses or operational counts.

**Signature.** The gravitational Core shows the actual reported agent constellation. Native
controls beneath it remain fully usable when graphics or the PC connection are unavailable.

**Critique.** Space decoration across every editor would compete with the work. Keep the
signature concentrated in launch, crossings and Core; make working forms quiet, legible and
consistent. Core describes reported roles and receipts, never model weights or neural activity.

## Data and security

Core calls `/api/supervisor`, `/master`, `/run` and `/cancel` using the existing native API
client and bearer header. A scene receives only an allowlisted display snapshot. Tokens,
credentials and API mutation functions are never passed to scene HTML or JavaScript. Agent
selection is a display action; run, cancel and master controls stay native.

## Verification

The shared theme, header, business selector and form controls use the design palette, two
bundled font families, tonal 14px panels, 8px controls and visible focus/press/disabled states.
An original finite photon-ring launch and business portal concentrate the signature; Core
uses the real public local Three.js renderer. A roster and task inspector remain native.

`expo export --platform all --output-dir ../artifacts/phone-interstellar-export --max-workers 2`
completed for web, iOS and Android without dependency or SDK upgrades. Core fixture browser
verification passed at 320px and 390px: authenticated master/run/cancel payloads, agent/receipt
inspection, scene-to-native selection, token-free scene requests/HTML, no page errors or
horizontal overflow, and no supervisor polling after leaving. Screenshots and the report are
under `artifacts/phone-core-*`. The 390px fixture renders the actual vendored Three.js scene;
the 320px fixture exercises reduced-motion fallback. Neither contacts real engines.
The 320px fixture also backgrounds the app during a stalled master action, resumes, and verifies
that the reported switch state reloads and native controls recover. Snapshot tests verify the
renderer allowlist, escaped HTML delimiters and rejection of unsupported/unknown/oversized messages.

Reference-metadata validation now keeps Resonance's written direction usable if an older or
incomplete PC response lacks upload limits. Existing phone fixture routes distinguish music
reference reads from Social Studio uploads and supply real-shaped limits; upload assertions remain.
All existing four-workspace, creative-transaction and named-profile browser suites passed at both
320px and 390px after those fixture additions. The new Core suite includes the negative incomplete
reference-metadata case. The interface checker reports one existing native Modal opacity-animation
warning; it is not a layout animation, and the existing unsaved-edit confirmation is retained.

Expo export checks bundling, and browser checks do not establish native-device rendering or
release installation. Physical iPhone/Android rendering, authentication storage, native scene
navigation and final package installation still require device verification before those claims.
