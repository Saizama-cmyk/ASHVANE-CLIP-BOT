# Revamp validation — October 11, 2026

The local overhaul has a runnable Windows build and rebuilt phone screens. The checks below establish what was exercised; they do not establish earnings, platform monetization eligibility or human-level editorial judgment.

## October 11: published phone release and private editorial notes

The final source suite passed **495 tests**, with one skipped, in 106.25 seconds. The changes were pushed to the canonical `Saizama-cmyk/ASHVANE-CLIP-BOT` repository. Native [phone run 38143306146](https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/actions/runs/38143306146) succeeded and published **1.0.21** from `5a7f12c`. All seven downloaded release assets passed checksum and metadata checks. The actual IPA is ARM64 iPhoneOS with its release JavaScript; the APK has the expected version/package and preserves the prior signing certificate. Both contain the new Desk and Research screens. The raw update feed and stable `phone-latest` downloads match the release. Installation on a physical phone still requires its sideloader or Android installer; device playback and biometrics were not tested.

The final Windows runtime passed all ten isolated startup/API/asset checks and replaced the installed app. Its executable SHA-256 is `A511EE540B9E729157F08870B80D6AB7A057F4CDCF482709DA60C856899C119A`; the previous runtime is backed up under `artifacts/installed-ashvane-backup-20261011-public`. Authenticated checks confirmed normal-profile startup, the scheduled-publishing control, exact desktop JavaScript, and active Twitch discovery. Phone remote is enabled using the existing profile password; actual Wi-Fi, Tailscale IP and Tailscale HTTPS probes all answered.

Public writing now receives the selected cut's speech and its own video frames, never private reviewer reasons, ratings, suggested captions, evidence prose, visual assessments or discovery chat. Public metadata, comments and hooks are checked before rendering/uploading; missing or legacy copy waits instead of falling back to a judge caption. Custom templates and the final YouTube suffix are checked too. Tests include rejection controls, valid source dialogue and passing reviewer quotations, legacy databases, Studio and disabled-review paths. Analytics records the actual composed upload metadata, including YouTube truncation and suffix, rather than private judge titles.

Twenty public streamer Shorts were analyzed through downloaded chronological frames and captions. The [study](STREAMER-CLIP-STUDY.md) documents sources, view snapshots, observed arcs and limitations. Useful formats informed the writer prompt; the [YouTube guide](YOUTUBE-PUBLISHING.md) records official title/description/hashtag guidance. This is bounded qualitative research, not proof of global trends or revenue effects. The running trend scout also refreshed its configured sources after installation.

YouTube again confirmed `invalid_grant` for the saved login. That revoked local token was backed up and removed so the app correctly requests **Settings → Accounts → YouTube → Connect** instead of presenting it as usable. Google displayed a sign-in form; the user must complete that login. No video was uploaded during verification. Automatic publishing therefore remains dependent on renewed account authorization and the existing review gates.

Evidence: `artifacts/final-public-phone-tests.log`, `public-copy-packaged-verification.log`, `public-update-install.log`, `phone-remote-installed-verification.json`, `youtube-login-verification.json`, and `phone/.expo/released-1.0.21/release-verification.json`. Earlier sections below describe historical checks and are superseded where the final state above differs.

## October 11: desktop editor and Shorts direction

The complete source suite passed **480 tests**, with one skipped, in 108.18 seconds. The new desktop opens in Clips with a source bin and actual portrait video monitor. Browser checks exercised authentication, keyboard clip selection, inline playback, detailed review, Studio navigation, Research and all **496** settings controls. The 390px layout had no overflow or JavaScript errors. A separate batch-publishing browser pass covered nineteen checks and four widths (1440, 900, 390 and 320), including partial failures, repeat-click prevention, missing media and reload recovery. These checks intercepted publishing requests; no real uploads were sent.

Five streamer Shorts were inspected with chronological frames and native English captions: four October 4 samples plus the highest ranked item from a fresh October 11 feed scan. That scan returned twelve recent Shorts from KaiCenatLive, Rayfist and kickzrust with no source errors. First-snapshot rates are labeled lifetime views divided by age; they are not measured growth. The app now retains per-item observation dates and linked descriptions, measures view gains when two observations exist, and excludes stale writing examples. This covers configured samples, not global YouTube trends or private retention.

The judge and writer now recognize everyday comedy, gaming stories, social exchanges and sincere commentary without requiring loudness or invented stakes. Titles and descriptions stay grounded in the candidate's transcript and timestamped viewer evidence. Mandatory hype and default lexical rejection were removed; configurable quality thresholds were preserved. The corresponding existing live prompt settings were updated before packaging and checked again on October 11.

Evidence: `artifacts/editor-shorts-final-tests.log`, `editor-final-browser-report.json`, `editor-batch-browser-report.json`, and [the sourced Shorts study](SHORTS-STUDY.md).

The Windows package passed all ten isolated startup/API/asset checks and was installed at `C:\Users\wilco\AppData\Local\Programs\Ashvane`. The prior runtime is preserved under `artifacts/installed-ashvane-backup-20261011-editor`. The normal profile initially could not start because E: was unavailable and its log folder was on that drive. After backing up settings, only the four unavailable buffer/work/clips/log folder overrides were cleared to use local defaults. Existing database media paths were not rewritten or moved. The installed runtime then passed the authenticated state, batch-control and exact JavaScript checks. No live uploads were triggered by verification.

The app's existing seven-day retention process expired 219 old candidate records on startup, including the stale scheduled queue. Google also returned `invalid_grant` for the saved YouTube refresh token: the connection must be renewed through Settings before YouTube uploads can work. A configured account flag alone does not establish a valid login. The previously installed local Ollama service was stopped; it was started again without downloading models.

## October 4: connections and scheduled publishing

The updated source passed **472 tests**, with one Windows symlink test skipped. A packaged startup check passed authentication, state, research, setup, schema, the batch endpoint and exact desktop assets. Archive inspection confirmed the package includes the storage startup and reverse-order move fixes.

**Publish all scheduled now** snapshots the full scheduled queue and the enabled, connected platforms. It runs sequentially through the existing review and upload checks, skips schedule waits/caps, reports each platform result, and preserves failed/held clips. Shared locks and a successful-post recheck prevent concurrent manual, automatic and batch uploads from duplicating a post. Browser checks passed repeat-click prevention, progress, partial failures, escaped error text, empty/disconnected states, navigation/reload recovery and a lost start response at widths 1440, 900, 390 and 320.

Live Twitch authentication, category queries and complete discovery with actual trend boosts succeeded after resolving broadcaster IDs to channel logins. YouTube token refresh, the connected channel query and resumable-upload initialization succeeded. **No video bytes or public upload were sent during validation.** The unsupported automatic 18+ metadata was removed; the user's explicit choice to disable the corresponding hold was saved. Twitch discovery was enabled in the existing settings.

All nine older scheduled candidates were missing both original and finished media at their saved paths. They cannot upload without restored media or newly captured clips. Missing scheduled media now becomes a visible failure. Drive-root scratch/clip/log settings were replaced with separate `E:\Ashvane` role folders; cleanup rejects roots, overlapping protected folders and links. Storage tests cover exact candidate-path repair, reverse-order moves and failed database transfer without opening an empty replacement database.

Evidence: `artifacts/connection-batch-final-tests.log`, `publishing-batch-browser-report.json`, `live-connection-validation.log` and `packaged-smoke-report.json`. The historical October 3 statements below describe that earlier verification; the October 4 settings changes above supersede its unchanged-live-settings claim.

## Engine and publishing gates

The complete project suite passed: **368 tests** in 115.60 seconds. Tests cover evidence validation, real frame extraction, final-cut review, model cancellation and lock recovery, bounded response repairs, research persistence and retrieval failures, and refusing an upload when final review fails. No real platform upload was performed.

The balanced clipping workflow sends actual chronological frames directly to the viewer judge instead of first spending a separate model call on a visual description. A second review inspects the rendered cut with its frames and timed speech. Both use a configurable response-token limit. Missing evidence, unresolved issues, failed quality checks or an unavailable reviewer hold publication when review is enabled.

Two saved clips were inspected using the installed local model and cached speech recognition. A short gameplay clip was held for inadequate context and payoff. A reaction clip passed source and final review with timed observations; the latest combined review took **17.0 seconds**, excluding speech recognition. An earlier uncapped request timed out; generation limits and compact repairs address that bottleneck, and stage timers make future delays visible. These few examples are a smoke check, not a calibrated editorial benchmark. Reports are under `artifacts/live-viewer-*.json`.

## Research

Live source refresh returned eight linked Counter-Strike 2 entries. The other starter feed returned no usable recent entries, which remains visible as a source error. Saved scripts and all five platform text outputs were produced by local director, scriptwriter and evidence-judge roles. Unsupported wording and incomplete claim citations were held even when the model gave an optimistic assessment. No live original draft was verified as ready for automatic publishing.

Research currently produces source-linked scripts and post copy. Original narrated video production and research auto-publishing are not implemented. The feed selection is a starter configuration and needs to match the intended channel audience. Source matching and model interpretation remain fallible.

## Desktop and phone

Final desktop browser verification passed: Today and Research loaded, all **493** settings appeared exactly once, eight sources were displayed, and no JavaScript errors or page overflow occurred. Earlier checks covered twelve responsive layouts, navigation, source selection and empty states. Real draft verification covered 83 sentence checks and eighteen exact clipboard copies without mutation requests. Reports are in `artifacts/browser-report.json`, `artifacts/desktop-interactions-report.json` and `artifacts/desktop-real-drafts-report.json`.

Phone web, Android and iOS/Hermes exports passed. Phone screen checks covered real sources, saved scripts, all five platform outputs, evidence disclosures and held-draft warnings. Publication-denial and uncertain-upload handling were tested with simulated responses. No APK or IPA was produced on this Windows machine; the Android toolchain is absent and iOS requires macOS. Device installation, media playback, sharing and biometrics remain unverified. Details are in `PHONE-REVAMP.md`.

## Running it

Use `START-REVAMP.bat` at the repository root. It selects `artifacts/windows-revamp/Ashvane/Ashvane.exe`, with a local-source fallback. The packaged startup check uses a separate disabled-capture profile and verifies authentication, state, setup, research, settings schema and exact desktop assets. Its result is `artifacts/packaged-smoke-report.json`.

Tests and previews used isolated data. Existing live profiles, credentials and clips were not edited. An intermediate packaging command did replace the repository's older generated `dist/Ashvane` folder; the final build has a separate destination. `artifacts/pre-revamp-tracked-source.zip` preserves the original tracked source from Git HEAD, excluding pre-existing uncommitted changes. No release, repository push or live publishing was performed.
