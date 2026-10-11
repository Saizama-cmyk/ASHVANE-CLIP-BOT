# Stories release — 11 October 2026

Stories is the second main section on desktop and phone. Original observatory styling
extends across the app, with a central black-hole transition and a reduced-motion fade.

The independent creation workflow accepts an original premise, nine horror genres,
still illustrations or animated shadow theatre, and a target length. Local director,
writer and jury roles produce the manuscript, scene plan and public metadata. Bounded
editorial repair returns to a fresh jury; rejection never becomes approval by retry alone.
Windows speech, installed local Kokoro narration and an optional local speech server
are supported. Both formats render actual narration, captions and video. Animated
shadow theatre is layered illustration animation, not generative cinematic footage.

The Stories queue has its own destinations, privacy, daily cap and posting gap. It reuses
the connected platform adapters, verifies account identity and checks the current
review and exact media/copy before uploading. Private agent notes do not enter the
renderer or outgoing metadata. Interrupted or ambiguous uploads are held to avoid
duplicates. Account credentials and platform capabilities still determine availability.

Validation for this release:

- 545 Python tests passed; one existing test skipped.
- Desktop verification: 56 UI checks at four widths, plus real backend/browser checks.
- Phone verification: 12 browser UI checks; iOS, Android and web exports passed.
- Actual local Gemma3:12b generation: an original four-scene story passed its jury;
  weaker samples remained held. This is a functional check, not a content-performance claim.
- Production-size 720×1280, 24 fps Kokoro videos contained decodable narration.
  Paired still/animated checks measured character motion and no-subject atmosphere
  above the matching still-image codec baseline.
- The frozen Windows executable served the exact desktop assets and Stories routes;
  its bundled neural worker produced a nonsilent 3.7-second WAV.
- Phone 1.0.22 IPA and APK were built, published, downloaded and checksum-verified.
  Both contain Stories and the portal transition; Android signer continuity passed.
  Physical-device installation/playback is not verified by these checks.

The native downloads are available in the
[phone release](https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/tag/phone-latest).
The bounded video study, exact sample sources and official policy references are in
[the research report](HORROR-STORY-RESEARCH.md). Automatic trend ingestion and
own-channel performance learning for Stories are future work, not features demonstrated
by this release. No remote account uploads were made by validation probes.
