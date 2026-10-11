# Resonance production research — 11 October 2026

Question: which production decisions help creator-specific AI music, and what can
local REAPER automation actually verify? This research informs the implementation;
it does not establish professional musical quality or income potential.

## Decisions that matter

**Preserve the idea before polishing the sound.** Nick Messitte describes comparing
the client's rough mix and relevant references at matched loudness. Rob Kirwan's
first-person Hozier interview describes retaining a distinctive original vocal
while replacing weaker backing. Tony Maserati describes protecting the client's
rough-mix intent and saving a new session. These are producer practices, not a
controlled trial proving an automated workflow works. Resonance keeps source audio,
works in revisions and carries the creator's brief through planning and review.
Sources: [Messitte](https://www.izotope.com/community/blog/13-tips-for-using-references-while-mixing),
[Kirwan](https://www.soundonsound.com/techniques/inside-track-hozier-take-me-church),
[Maserati](https://www.soundonsound.com/techniques/secrets-mix-engineers-tony-maserati).

**Human feel requires musical choices.** Ableton separates timing, velocity and
randomization; uncorrelated random timing can even separate chord notes. The SOS
drum-programming discussion emphasizes playable patterns, intentional accents,
articulations and transitions. The inference for this system is to make deliberate
pattern changes rather than add random jitter as a quality shortcut. A rigid grid
can be appropriate for a requested genre. Current generated instruments are simple
original synthesized starters; they are not a realistic drummer or a premium sample
library. Custom notes support pitch, timing, velocity and duration, but repeat per bar.
Sources: [Ableton manual](https://www.ableton.com/en/live-manual/12/using-grooves/),
[SOS drum programming](https://www.soundonsound.com/techniques/programming-realistic-drum-parts).

**Arrangement and balance come before more processing.** Mike Senior discusses
timing, masking, phase, reverb and reference comparison as recurring mix problems.
Audrey Martinovich treats low-end decisions in full-mix context rather than through
a fixed EQ recipe. iZotope's dynamics guidance connects density and low-frequency
energy to limiter behavior. Resonance can change arrangement, levels, pan, EQ and
stock effects; its planner must not invent parameter names or promise that EQ fixes
an unsuitable performance, lyric or melody. Missing material prompts a source or
creative decision. Sources: [Senior](https://www.soundonsound.com/techniques/mix-mistakes),
[Martinovich](https://www.izotope.com/community/blog/7-tips-for-mixing-the-low-end),
[dynamics guidance](https://www.izotope.com/community/blog/9-tips-to-preserve-dynamics-without-sacrificing-loudness).

**A louder result is not automatically better.** Spotify's normalization policy and
EBU's broadcast recommendation serve different playback contexts. ITU BS.1770
defines measurement algorithms; it is not a musical-quality verdict. Current
Resonance QC measures sample peak, RMS, silence, duration and clipping on actual
decoded channels. It does not yet implement an ITU loudness meter or oversampled
true-peak measurement. Do not label its sample peak as true peak, or apply one
universal LUFS target to every genre and destination. Sources:
[Spotify](https://support.spotify.com/us/artists/article/loudness-normalization/),
[EBU R128](https://tech.ebu.ch/publications/r128),
[ITU BS.1770](https://www.itu.int/rec/R-REC-BS.1770).

**Separated stems need listening.** Demucs documents automatic stem rescaling that
can change relative balance. A source-separation listener study found that metric
relationships differed by stem and tested system; its results do not justify a
single universal score. Resonance distinguishes a retained dry vocal from a stereo
master. Replacing backing requires real retained vocal/backing files and can still
leave separation artifacts. It never labels a complete stereo mix an isolated vocal.
Sources: [Demucs](https://github.com/facebookresearch/demucs),
[original listener study](https://arxiv.org/html/2507.06917v3).

**Evaluate multiple dimensions and keep evidence honest.** SongBench proposes
expert evaluation across vocals, instruments, melody, structure, arrangement,
mixing and musicality. It is one research origin, not an independent certification
of our models. Resonance's review considers brief alignment, groove, intelligibility,
artifacts, masking and translation only when evidence exists. A local listener
observation is tentative; no text model claims it heard audio. An unavailable
listener produces an audition-needed state with the saved revision, not approval.
Source: [SongBench original paper](https://arxiv.org/html/2604.25937v1).

**Render from reproducible source and use the workstation itself.** YuE2's generation
documentation distinguishes symbolic/editable inputs, generated audio and retained
generation artifacts. A playable file can still represent incomplete generation.
REAPER documents embedded Lua and native project/track/FX APIs. Our adapter accepts
validated data, generates trusted native operations and renders through REAPER;
the model cannot submit scripts or arbitrary paths. Sources:
[YuE2 repository](https://github.com/multimodal-art-projection/YuE),
[generation guide](https://github.com/multimodal-art-projection/YuE/blob/main/docs/generation.md),
[YuE2 workflow](https://github.com/multimodal-art-projection/YuE/blob/main/skills/yue2-music/SKILL.md),
[ReaScript](https://www.reaper.fm/sdk/reascript/reascript.php),
[native API](https://www.reaper.fm/sdk/reascript/reascripthelp.html).

Ozone 8's historical Master Assistant documentation provides a useful design
example: analysis needs a representative audio section and supplies a starting
point. It is not a recommendation to buy or install that product. No paid plugin
was added. [Historical documentation](https://downloads.izotope.com/docs/ozone8/master-assistant/index.html).

## Audition procedure and remaining work

1. Write concrete requirements: genre, mood, tempo feel, instruments, vocal role,
   song sections and what must remain unchanged. Reference desired qualities rather
   than promise imitation of another performer.
2. Listen to the source before editing. If composition or performance is wrong,
   regenerate or request a clearer decision; mixing cannot recover absent material.
3. Compare source and revision at matched playback loudness. Check the whole song
   plus transitions, vocal consonants/sibilance, low end and loudest sections.
4. Check headphones, ordinary speakers and mono. Retain both versions and record
   why the selected one serves the brief. These human translation checks are not
   yet automated or claimed as passed.
5. Approve a private audition before any external release. No music distributor or
   publishing connector was introduced in this change.

The implemented producer is bounded to the configured iteration budget and trusted
editing actions. It can ask for input, preserve a failed revision and cancel owned
work. It does not support arbitrary instruments, unrestricted song restructuring,
automatic vocal performance replacement or guaranteed mastering quality.

Local tests validated API contracts, plan rejection, cancellation, source preservation
and recovery. The REAPER startup/evaluation screen prevented an actual native export;
there is no successful edited WAV, listening result or all-genre creator audition
benchmark yet. Finish the PC's REAPER first-run setup before that acceptance test.

## Evidence accounting

The linked sources were read through web access or browser DOM when the publisher
blocked direct fetching. Vendor manuals establish their own contracts; interviews
establish the interviewees' reported practice; the two studies are distinct research
origins. Multiple pages from REAPER, YuE or iZotope are not independent corroboration.
The installed research skill's local page-reduction tools were unavailable, so
direct reading was used. No raw page corpus is committed.

The machine-readable origin ledger is `music-production-ledger.json`. Single-origin
warnings are intentional for authoritative API documentation and individual studies;
they are not hidden as consensus. This document separates those sources from the
implementation choices and the native verification gap.
