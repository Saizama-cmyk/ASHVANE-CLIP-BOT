# Inside Ashvane

Technical and operating briefing · evidence snapshot: 14 October 2026

[Company briefing](COMPANY_BRIEFING.html) · [Current status](STATUS.md) ·
[Setup](SETUP.md) · [AutoClip comparison](AUTOCLIP_COMPARISON.md) ·
[Improvement priorities](IMPROVEMENT_PRIORITIES.md)

## 1. The company and the product

Ashvane is an owner-operated media production workbench. It combines four distinct
businesses on one Windows workstation: **Surge** for streamer clips, **Hollow** for
original scary stories, **Resonance** for music, and **Social Studio** for client
content. The desktop dashboard and native phone project expose the same underlying
business records. **Core** is shared maintenance infrastructure, rather than a fifth
business or a media publishing account.

The operating premise is local control: local inference, inspectable files and
queues, separate destination identities, and recorded evidence for consequential
changes. This reduces dependence on hosted inference subscriptions. It does not
remove hardware, electricity, storage, software-license or operator costs. Local
execution also does not make third-party platform requests, account connections or
publishing offline.

Revenue comes from whatever a creator or client can legitimately achieve with the
outputs. Neither a model score nor automated posting establishes demand, licensing,
monetization eligibility or income. There is no guaranteed audience size or revenue
target built into this briefing.

![Ashvane architecture: owner interfaces, four workspaces, shared local infrastructure and authorized destinations](brand/architecture.svg)

## 2. The owner experience

The business selector changes the working context. Its separate Run/Stop switch
changes whether that business accepts expensive work. Selecting a workspace never
starts an engine. Stopped businesses retain readable saved work, and stopping one
does not switch the others off. Work already handed to a provider may need to drain
or retain an uncertain outcome; a switch is not a transaction rollback.

Surge's **Clips** workspace centers the actual media preview and source bin. The
review explains acceptance or a hold; Studio changes trim, layout, captions and
hook. **Live** exposes selected streams, capture health, preview and event signals.
**Today** summarizes activity. **Research** collects public evidence and produces
reviewable scripts and platform drafts. **Growth** displays retrieved outcomes and
permission/data states. **Setup**, **System**, **Storage** and generated **Settings**
expose prerequisites, hardware choices, data locations and tunable behavior.

Hollow exposes premise, manuscript, scene direction, narration, visual treatment,
render preview, review and separate publishing accounts. Resonance's Create desk
handles reference recordings, lyrics and generation; its production desk handles
auditions and editable REAPER revisions. Social Studio organizes client facts,
brand rules, styles, drafts, assets and a manual calendar. Shared Tools include
optional Assistant and Code workflows; their presence does not grant them another
business's destination credentials.

The interstellar design concentrates its original photon ring in launch,
business crossings and Core. Ordinary production forms stay legible. The Core
observatory visualizes reported agents and receipts; it is not an image of neural
weights or a simulation of consciousness. Missing measurements remain unknown,
and decorative motion is not evidence that work finished.

Sources: [business boundaries](BUSINESSES.md), [runtime controls](../clipbot/business_runtime.py),
[desktop design](INTERSTELLAR_DESIGN.md), [phone design and checks](PHONE_INTERSTELLAR.md).

## 3. Surge: from a live signal to a finished clip

Discovery selects Twitch and Kick sources from configured categories, popularity
and named streamers. Capture uses Streamlink and ffmpeg to maintain rolling media
segments. Chat-rate, keyword and audio-level changes identify candidate moments.
They are intake signals, rather than judgments that a clip is entertaining.

The assembler cuts from the rolling buffer and checks actual stream presence,
duration, black frames and silence. Faster Whisper supplies timestamped words.
Ordered video frames and the transcript then reach the local clip judge. Depending
on the configured profile, the multimodal judge sees the frames directly or receives
a separate visual description. The viewer rubric asks whether a stranger can
understand the opening, context, payoff and pacing. Low confidence, blocking flags
and missing evidence can veto an otherwise high score.

Accepted candidates receive separate public copy grounded in the video. The editor
uses ffmpeg to render the configured vertical layout, optional facecam composition,
word captions, hook, watermark, zoom, pause removal and intro/outro. Safety settings
control caption masking and audio bleeps. The saved edit timeline maps source words
and observations into final-video time.

The finished-media gate examines the export. It combines technical QC, frame review,
mapped speech, the public drafts and composed destination metadata. Its public-claim
check includes titles, descriptions, messages, tags, credits and template/suffix
text. Saved duration must agree with the actual export within configured tolerance.
Approval fingerprints include actual media bytes and review inputs, so a stale
approval is invalidated when relevant text, evidence, settings or video changes.

Opening-audio detection compares bounded decoded spectra with the aligned source
when available. It targets newly introduced sustained broadband noise. This is
neither a listening test nor proof that the entire soundtrack is artifact-free.
Missing source alignment is labeled unavailable; source/game noise must not be
mistaken for edit-created static. Caption review uses sampled images and saved
timing, and cannot establish that every caption was inspected.

The scheduler applies configured caps, gaps, posting windows and retry limits.
The pre-upload gate also protects older queued clips. Studio replacement and
upload share a media mutation lock. Explicit publish-now/batch actions bypass
ordinary schedule limits while retaining the quality gate. Platform results are
recorded independently, and an already successful destination is not blindly
uploaded again.

Sources: [pipeline](../clipbot/pipeline.py), [capture](../clipbot/capture.py),
[judge](../clipbot/clipability.py), [editor](../clipbot/editor.py),
[final gate](../clipbot/review.py), [publication checks](FINAL_PUBLICATION_CHECKS.md),
[scheduler](../clipbot/scheduler.py).

## 4. Publishing identities and destination support

Surge and Hollow have independent account profiles. Every generated item remains
bound to its originating profile; legacy work belongs to the main profile.
Switching to another channel holds the old queue rather than retargeting it. Active
uploads, generation and pending authorization also constrain profile switching.
Unreadable identity data is preserved and causes a hold instead of a silent reset.

OAuth app registration identifies the software to a provider. A signed-in user,
channel token, Page token or webhook identifies a publishing destination. The first
may be reused under documented conditions; the second is never inherited by a new
business or profile. A saved public profile URL is descriptive, not authorization.

| Workspace | Implemented destination adapters | Boundary |
|---|---|---|
| Surge | YouTube Shorts, TikTok, Instagram Reels, Facebook Page Reels, Discord | Connected account, provider approval and configured publisher required |
| Hollow | Its own publishing accounts through story publishing | Separate credentials, queue, profile and authorization |
| Resonance | No music distribution/release publisher | Native exports are private auditions |
| Social Studio | No connected automatic publishing | Public profile links and manual calendar only |

Official APIs do not guarantee quota, copyright clearance, account standing or
reach. TikTok audit/privacy requirements, Meta account permissions and Google
project/API permissions remain external prerequisites. Consult the provider's
current developer documentation and Ashvane's actual connection status.

Sources: [account profiles](../clipbot/account_profiles.py),
[business/account design](BUSINESSES.md), [publishers](../clipbot/publishers),
[Hollow publishing](../clipbot/story_publishing.py).

## 5. Hollow: original narrative production

Hollow creates original narrator-led scary stories. A creator can supply a premise
or request an editable local suggestion. Director, writer and jury roles structure
and assess the script. Scene direction describes visible moments and reveal order;
it is distinct from narration and public promotional copy.

Narration can use Windows speech, installed local Kokoro assets or the configured
local compatible speech service. Real audio duration drives scene timing. Visual
choices include supplied artwork, explicit procedural shadow theatre, an existing
AUTOMATIC1111 service, or a dedicated local ComfyUI installation. FLUX.2 Klein **4B**
FP8 is the documented illustration checkpoint. Actual generated movement can use
Wan 2.2 TI2V 5B; camera-only movement is a different, labeled treatment. A still image
with a moving camera is not advertised as generated character motion.

Models and ComfyUI are external installations. Managed children bind locally and
use bounded jobs, output validation and owned cancellation. Unavailable requested
AI artwork fails visibly instead of silently substituting another style. Longer
animated narration uses additional motion segments, rather than claiming a looped
short segment is a complete new performance. Finished video, captions and review
precede separate publishing.

Consistency of people, props and scenes still needs inspection. Generated motion
does not guarantee acting, lip sync or narrative fidelity.

The compilation workflow now assembles approved finished stories in a chosen order,
preserving their existing performance and visual treatment through normalized
reencoding. It keeps edition-owned source copies, measured chapters and optional
silent title cards; landscape is the default, with portrait available. It uses the
existing single job slot, cancellation and profile-owned publishing workflow. The
checks cover source approval and assembly, rather than claiming a new creative jury,
narration or generated artwork. Real ffmpeg source checks, the full suite (1,110 passed; five skipped) and 70 frozen
application checks passed. The frozen run assembled a synthetic seven-second
compilation through the Hollow API. The installed release serves matching assets
and retains private-endpoint authentication; a production creative-quality verdict
is not implied.

Sources: [story orchestration](../clipbot/stories.py),
[rendering](../clipbot/story_render.py), [visual setup and limits](HOLLOW_LOCAL_VISUALS.md),
[compilation contract and evidence](HOLLOW_COMPILATIONS.md),
[release evidence](STORIES-RELEASE-2026-10-11.md).

## 6. Resonance: music creation and native revision

Resonance connects to the existing local LocalSongLab bridge. It can generate a
take, accept supplied or generated lyrics, use an instrumental mode, and retain
available dry vocals. Reference uploads are authenticated, bounded and analyzed
locally. Written observations can inform direction and lyrics; they do not directly
condition YuE2 audio, clone a reference voice or guarantee a matching sound.

The production workflow prepares a real editable REAPER project. Original masters
remain reference tracks. Editable beat/melody data and MIDI sidecars remain distinct
from a complete stereo mix. The local producer interprets a brief into validated,
bounded operations, edits a new revision, requests a native export and measures the
decoded audio. A model cannot submit arbitrary native scripts or untrusted paths.

A recorded native check changed gain/pan, read back the change and exported a
non-silent one-second 48 kHz stereo PCM24 WAV. That establishes operation of the
tested path, rather than a finished song or subjective quality. Current QC measures
duration, sample peak, RMS, silence and clipping. Sample peak must not be relabeled
as oversampled true peak. Optional local listening is a tentative observation and
remains unavailable when that model did not actually run.

Resonance does not distribute music or automatically approve a commercial release.
REAPER is separately licensed software; Ashvane's AGPL license does not license
REAPER, external models, references or generated works on their behalf.

Sources: [bridge integration](../integrations/localsonglab),
[producer](../clipbot/music_producer.py), [music API](../clipbot/music_api.py),
[production evidence and research](MUSIC_PRODUCTION_RESEARCH.md), [business evidence](BUSINESSES.md).

## 7. Social Studio: client context before output

Social Studio keeps each client's documented facts, public profile links, brand
guide, saved styles, drafts, references and calendar together. Client/style scope
constrains retrieval. Local AI can propose ideas and write draft content using that
context, while the owner can retain supplied text and edit the result.

Image and video reference analysis uses the frames actually extracted. Audio and
PDF reference workflows currently rely on creator notes rather than a claim that
all source audio or document pages were understood. Failed/pending analysis is
visible. Historic media is reference material; it does not become fresh footage or
grant reuse rights merely because it was uploaded.

The manual publishing calendar is implemented. Destination sign-ins and automatic
Social Studio posting are not. This boundary matters for a client-facing operation:
a drafted post, scheduled calendar entry and published remote post are different
deliverables. The existing Social implementation cannot execute a client's project
code or silently borrow Surge/Hollow credentials.

Sources: [Social API and storage](../clipbot/social_api.py),
[workspace boundaries](BUSINESSES.md).

## 8. Core: maintenance with execution evidence

Core's local director starts with capability and model-health inventory, runtime
fault metadata, aggregate queue/resource observations and saved receipts. It can
investigate public sources, delegate bounded specialist work, read allowlisted
local text, discover supported extensions, propose code changes and retain outcomes.
All agents share a finite turn budget and the business GPU lock.

Idle-only admission defers inference while business generation owns resources.
Continuous capture watching alone is not treated as active clip generation.
Configured public research feeds can be prepared without competing inference while
the director waits. Blocking codes, wait age and next scheduled checks explain
actual state. Missing decision inference and missing engineering weights are
separate problems: decision work can be ready while repair work is blocked.

![Core repair gates: observe, plan, stage, isolated checks, independent review, source promotion; holds and rollback](brand/core-pipeline.svg)

An engineer stages a bounded patch against current source hashes and supplies an
executable reproduction. Isolation requires Docker, not candidate execution on the
host. The protected baseline suite and configuration stay immutable. Original-code
reproduction must fail for the expected assertion; the candidate must pass both
regressions and the reproduction. An independent reviewer sees the actual patch.
Missing isolation, weak reproduction or stale hashes hold promotion.

When enabled and eligible, promotion writes source atomically and stages a
hash-pinned runtime overlay. Protected loaders and privacy/isolation boundaries are
not autonomously replaceable. Activation waits for business work to drain, and
startup health acknowledges the overlay. Unconfirmed/tampered activation restores
the previous overlay on the next launch. Source rollback respects subsequent owner
edits. Native dependencies and internal frozen helpers may require a normal rebuild.

Tool requests and tool returns have distinct durable records. A requested action is
not a successful result. Saved receipts distinguish completed, partial, failed,
interrupted and budget-exhausted work. Training exports contain only eligible
examples with provenance; untested answers and unknown reuse rights remain
quarantined. This is outcome memory and dataset preparation, **not model-weight
training, consciousness or an automatic increase in intelligence**.

The demonstrated local repair used Qwen3-Coder and an independent reviewer to fix a
disposable UUID-format example, with actual Docker checks, source application and a
reversible overlay. One eligible example was retained. This is a narrow test of the
repair mechanism. It did not repair production Ashvane, and it does not establish
general autonomous reliability.

A later count-only read of the installed production ledger recorded 11 events, two
tool receipts, two jobs and four public sources, with zero production examples and
zero source-applied changes. These are real activity counts, not successful repair
counts. The eligible example from the disposable trial belongs to separate test
evidence and must not be mixed into production outcomes.

Sources: [Core design](SUPERVISOR.md), [reality audit](CORE_REALITY_20261013.md),
[runtime evidence boundary](CORE_RUNTIME_EVIDENCE.md),
[repair controller](../clipbot/supervisor_changes.py),
[isolation](../clipbot/supervisor_sandbox.py), [extension boundary](SUPERVISOR_EXTENSIONS.md).
The raw disposable repair receipt is maintained locally in
`artifacts/supervisor-local-repair.json`; public prose omits its temporary paths.

## 9. Learning from editorial and audience outcomes

Surge saves good-clip/wrong-rejection corrections with the original profile and
source/judge provenance. They survive media cleanup. Source-group holdouts prevent
the same source from appearing in training guidance and evaluation. Proposed judge
changes need sufficient held-out good/bad examples and no increase in either kind
of error. Saving feedback itself does not change thresholds or publish anything.

Growth retrieves available provider metrics and authenticates YouTube Analytics
reports separately from basic upload permissions. A recorded live request asked
for eight tracked videos and returned five rows, including available view/watch
and subscriber fields. The other three remain unavailable; they are not zero.
Small samples, missing scopes, service-disabled responses and unavailable retention
are explicit states. A model's estimated virality is not measured audience response.

Creative memory retrieves profile/client/style-scoped feedback and direction for
future prompts. It does not train the underlying model. Private feedback and
evaluation notes must stay outside public titles, captions and scripts.

Sources: [editorial corrections](CLIP_FEEDBACK.md),
[analytics](../clipbot/analytics.py), [YouTube outcome integration](YOUTUBE_OUTCOME_LEARNING.md),
[creative memory and profile scope](BUSINESSES.md).

## 10. Shared resources, storage and privacy

Bounded workers and admission limits keep capture, transcription, inference,
editing and creative jobs from all expanding unchecked. Capture storage work uses
its dedicated bounded pool; cached health reads do not rescan capture drives on
the engine loop. Queue phases and waiting reasons separate work waiting for a slot
from work actively running. Defaults are starting points, not hardware throughput
guarantees. The four manual business switches remain independent.

Configuration generates labeled Settings fields. The application owns its
database, profile settings and encrypted token stores on the workstation, with
configurable data/media locations. Windows DPAPI protects secrets under the
current OS user; a compromised signed-in user or host remains outside that
protection. Local profile authentication protects dashboard/API access. Phone
access requires the configured remote route and existing authentication, rather
than adding a hosted Ashvane account.

Networks remain necessary for source streams, public research, model/package
downloads, updates, account authorization, publishing and analytics. The bundled
Interstellar fonts do not require a font CDN. Local inference does not imply that
all network endpoints are absent; a user-configured remote model endpoint also
changes where inference data travels. No public briefing should publish private
media, token stores, callback URLs or personal filesystem paths.

Sources: [business runtime](../clipbot/business_runtime.py),
[storage worker](../clipbot/storage_io.py), [authentication](../clipbot/auth.py),
[settings](../clipbot/config.py), [privacy notice](../PRIVACY.md).

## 11. Phone and release reality

The Expo/React Native project provides the four-business interface and a shared
Core view. Native API requests use bearer authentication. The embedded Core scene
receives an allowlisted display snapshot and no tokens or mutation API functions;
native controls own master/run/cancel. Leaving Core or backgrounding/locking the
app stops relevant polling. Authenticated media uses private temporary caches.

Expo exports and browser fixtures verify bundling and selected flows, including
narrow layouts and reduced-motion fallback. They are not physical-device tests.
A new IPA for the Interstellar revision is pending the native CI workflow at this
snapshot. Existing release/feed addresses remain stable, but their existence is
not proof that the latest source is installed or signed. No physical iPhone
rendering, new IPA installation or end-to-end device validation is claimed.

Windows source, staged frozen build and installed runtime are also different
states. A passing source suite does not mean an older installed executable includes
that source. Release validation must match the built commit/assets and retain
startup/API evidence. See [status](STATUS.md) rather than inferring release state
from the date of this document.

Sources: [phone project/setup](../phone/README.md),
[phone verification](PHONE_INTERSTELLAR.md),
[packaged verification](../scripts/verify_packaged_app.py), [installer](../installer).

## 12. Licenses, requirements and remaining work

Application source is GNU AGPL-3.0; [LICENSE](../LICENSE) is authoritative.
[NOTICE](../NOTICE.md) records third-party components. Bundled Space Grotesk and IBM
Plex Sans carry their OFL notices. External model checkpoints, ffmpeg builds,
Windows, REAPER and supplied source media have their own terms. Free access to a
checkpoint or a locally generated output is not a blanket commercial-rights grant.

The core development stack is Python 3.12, FastAPI, SQLite, ffmpeg/ffprobe,
Streamlink, faster-whisper and Ollama. NVIDIA acceleration is useful but model size,
RAM, VRAM, storage bandwidth and active work determine real capacity. Hollow image/
motion engines, Kokoro voices, LocalSongLab/YuE2, REAPER, Docker and phone toolchains
are additional prerequisites for their respective features, not bundled promises.

The highest-value next work is to preserve reliable source/runtime parity, validate
native phone builds on hardware, expand held-out media-quality evaluation, and
calibrate outcome learning on actual sufficient samples. Long-video import,
variant comparison, speaker tracking and broader publishing are prospective
improvements rather than implied parity with hosted clipping services.

This briefing was checked against repository source and existing evidence records.
It did not run new production jobs, publish media, benchmark AutoClip, install a
phone package or establish an earnings forecast. Detailed proposed work and
tradeoffs are in [improvement priorities](IMPROVEMENT_PRIORITIES.md).
