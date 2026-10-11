# Phone content desk

**Released October 11: version 1.0.21.** The [native build](https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/actions/runs/38143306146) succeeded. The actual [iPhone IPA](https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/Ashvane.ipa), [Android APK](https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/Ashvane.apk), update feeds, package reports and checksums were downloaded and verified. Both contain the new Desk and Research screens; Android preserves the previous signing certificate. The update feed now points to 1.0.21. The installed PC answers through Wi-Fi and Tailscale with the existing profile login. The unsigned IPA still needs the user's sideloader; installation and physical-device behavior have not been verified.

The phone opens on **Desk → Today**. It shows the PC's actual stream monitors, active pipeline jobs, scheduled/posted/rejected stage counts with their time window, recent cuts, publishing connections, and real post results. Live, Clips, Studio, Settings, and Log remain within Desk. **Research** is a primary destination; Assistant and Code are under **Tools**.

Research uses the authenticated `/api/research` contract in `REVAMP.md`: refresh public sources, choose linked evidence, request an original topic draft, inspect each agent's current state, read scripts and separate platform copy, open HTTP(S) source links, and share the text using the native share sheet. Deletion requires a confirmation. It never labels text as a produced video or auto-publishes research drafts. Source freshness and failures remain visible with previous useful data.

Draft reviews lead with the enforced approval/grounding decision and claims that require verification. A held draft visibly says **Needs review** even if the model's explanation sounds positive. The detailed sentence audit is available in an accessible disclosure so it does not bury the script and platform copy.

Clip reviews expose real verdict reasons, observed visuals, transcript, opening hook, viewer hook/context/payoff/pacing/confidence, why someone would watch or skip, evidence timestamps, flags, and the final rendered-video review. Manual posting is limited to selected enabled/configured platforms and requires a confirmation. The existing backend remains responsible for final publishing checks.

A final-review denial reloads the clip's current server status and keeps the rejection reason visible. An answered rejection does not mark the PC offline. Partial platform failures retain their reasons; a network timeout explains that an upload may still finish and asks the user to check post results before retrying. Final review badges distinguish Passed, Held, Unavailable, and Disabled.

Main status and research polling use an awaited request followed by a timeout, with a shared in-flight promise for manual refreshes. This prevents overlapping calls. Polling stops while the app is inactive, backgrounded, locked, or on optional tools. HTTP errors are visible; the PC connection indicator is not marked healthy until a state request succeeds. Optional downloaded AI weights are loaded only after opening Assistant or Code. The repeated animated launch overlay and live pet timer were removed to make daily checks immediate.

The existing warm-black/ember palette is retained. Secondary text has higher contrast, small buttons/icon buttons/segments have 44px minimum targets, selected tabs are announced, and buttons expose disabled/busy accessibility states. Research and settings have explicit loading, empty, retry, and failure states. String-list settings, including research feeds, are editable one item per line.

## Verification

- Babel parsed the modified phone screens successfully.
- Expo web, Android, and iOS exports passed, including native Hermes bundles.
- Importing the one used icon set directly reduced the web JavaScript bundle from 952 KB to about 557 KB (about 42%) and the native bundles from about 2.3 MB to about 1.99 MB. Unused icon fonts are no longer exported.
- Final combined web/Android/iOS output is under `phone/.expo/revamp-verified`, not signed installation packages.
- Playwright with installed Edge verified sign-in, Tools → Assistant → Desk, and the authenticated Today/Research screens against an isolated Preview profile at 390×844. No runtime errors or horizontal page overflow. Visual screenshots were inspected; the horizontal subnavigation height and research status layout were corrected after that inspection.
- A repeat browser pass matched the Preview backend's eight actual sources to the Research screen and selected a source. The isolated browser disabled CORS enforcement to test native-equivalent requests; the backend does not permit an ordinary cross-origin web preview sign-in from port 8791. This does not affect native React Native requests.
- After existing real research results were loaded into Preview, Playwright checked held drafts `d8bc13015732476a9050985fa3196ee5` and `4f8c75dff0974dec8498cca9be5b3e87` at 390×844: complete scripts, separate YouTube/TikTok/Instagram/Facebook/Discord outputs, all four/eight unsupported-claim warnings, linked source evidence, and opening/closing the review audit. The enforced hold stayed visible; no runtime errors, horizontal overflow, generation requests, deletions, or publishing requests occurred. Native exports were regenerated after the review layout fix and passed.
- Saved evidence is under `phone/.expo/phone-draft-verification.json` and `phone/.expo/phone-draft-*-review.png`, `*-script.png`, `*-youtube.png`, `*-tiktok.png`, `*-instagram.png`, `*-facebook.png`, `*-discord.png`, and `*-evidence.png`. The reproducible read-only check is `phone/.expo/verify-drafts.cjs` against Preview on 8788 and the exported phone web preview on 8791.
- The actual Clips component was exercised with simulated request responses: final-review denial reloaded the rejected cut, retained the explanation, removed its posting action and did not mark the connection offline; a transport timeout retained the warning about an uncertain upload. These checks did not make real publishing requests.
- The interface skill's static checker reported no findings in the modified screens, and `git diff --check` passed.
- No real account publishing, live data mutation, or signing/device installation was used for verification.

Physical-device playback, native share dialogs, biometrics, and signed installation remain device checks. The phone continues to require the PC to be running for capture, research agents, rendering, and publishing.

## Installation package limits

This Windows machine has no configured Android SDK, Gradle cache or command, or full JDK (`javac`); Java runtimes used by games are not sufficient. No APK was produced locally. Native Hermes exports verify bundling but are not installable APK/IPA packages. iOS packaging requires Apple's macOS toolchain. The existing `.github/workflows/phone-ipa.yml` defines Android APK and unsigned iOS IPA builds on GitHub runners; that release-publishing workflow was not dispatched during verification.

## Release verification — October 11, 2026

- Confirmed the canonical public repository is `Saizama-cmyk/ASHVANE-CLIP-BOT`, default branch `main`. The existing phone workflow last succeeded in run `35935825945`, producing `phone-v1.0.20` with both IPA and APK; this is the previous build, not the revamped source.
- Downloaded that actual 12,118,152-byte IPA and ran both new package inspectors against it. Its unsigned ARM64 iPhoneOS executable, bundled release JavaScript, version/build `1.0.20`/`20`, minimum iOS `15.1`, and three privacy declarations passed. The inspectors correctly reported no embedded entitlements; they do not invent entitlements from Expo config. SHA-256: `833195d3016bfb11b17933f2cf2d622f679727e126f90a8129b373bdd41ee2ab`.
- All 22 phone package/manifest tests and the phone update comparison checks passed. Negative package tests reject a missing/empty JavaScript bundle as well as incorrect version, bundle identifier, architecture/platform, or executable. Workflow YAML parsed and its publish shell script passed `bash -n`.
- The release workflow pins Python 3.12 for artifact inspection, stamps each native binary from the workflow run number, associates release tags with the built commit, serializes phone publication, and refuses to replace a newer published version with an older rerun. Numbered release tags remain in place. It publishes package/permissions reports, `SHA256SUMS.txt`, `sideload.json`, and `altstore.json` alongside the installation files. An Android failure is stated in release notes while a verified iPhone build remains downloadable.
- Corrected the phone installation and update-source links to the canonical repository. An optional phone-model preparation failure now produces a visible tool error instead of an unhandled promise rejection.

Pushing this source to `main` automatically starts the phone workflow. A manual `workflow_dispatch` is only needed if no push run starts. The expected stable downloads are:

- `https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/Ashvane.ipa`
- `https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/Ashvane.apk`
- `https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/sideload.json`
- `https://raw.githubusercontent.com/Saizama-cmyk/ASHVANE-CLIP-BOT/main/docs/sideload.json`

The native installation files have now passed inspection, as recorded in the release note above. Installing the unsigned IPA still requires the user's existing sideloader and Apple ID; no signing credentials are needed by this build workflow. Physical-device playback, share sheets and biometric prompts remain unverified here.
