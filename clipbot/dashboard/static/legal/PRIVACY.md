# Privacy: Ashvane

Ashvane stores its production data locally and has no hosted Ashvane account,
central usage-tracking service or advertising service. Local operational telemetry
and authorized destination analytics are features of the app; they are not an
Ashvane-hosted tracking service. Network activity is described below.

- **Profile passwords** are not saved in plaintext. Local authentication stores a
  salted PBKDF2-HMAC-SHA256 hash; the current implementation uses 600,000 iterations.
- **API keys and tokens** use Windows per-user DPAPI encryption where enabled and
  available. Saved-key encryption is on by default. Older plaintext settings remain
  readable and are protected on a subsequent encrypted save; disabling that setting
  changes the at-rest protection of settings. Token stores use their encryption path.
- **Production data** includes settings, transcripts, media, logs, queues, feedback
  and maintenance evidence. The default Windows root is `%LOCALAPPDATA%\Ashvane`.
  Additional local profiles use their own folders; data/media paths are configurable,
  and `CLIPBOT_HOME` can override the root. An older `%LOCALAPPDATA%\ClipBot` folder
  is migrated when possible and may remain in use if that migration cannot complete.
  Uninstalling asks whether to delete application data.
- **Local AI** uses the installed engines and models, including Ollama and Whisper.
  A user-configured remote model/service endpoint changes where its input travels;
  local defaults must not be read as a promise about every possible configuration.
- **Business identities** remain separate. Surge and Hollow use their own destination
  profiles and token stores; a new profile does not inherit another signed-in channel.
- **Phone access** uses the owner's configured PC connection and authentication.
  Selected media may be cached privately for playback. The phone project uses bundled
  fonts, and its Core scene receives an allowlisted display snapshot rather than
  account tokens or mutation APIs.

**Configured features that contact other services:**

- Source discovery, stream/media retrieval and public chat from Twitch/Kick.
- Public research pages/feeds, and supported package acquisition when Core extensions
  are requested or enabled by its configured workflow.
- Account authorization, authorized uploads and available analytics from the platforms
  you connect: YouTube, TikTok, Instagram, Facebook and Discord. Their own privacy
  policies apply to data sent to them.
- Model/voice/engine downloads and dependency installation from their configured
  sources. An explicitly configured remote inference endpoint receives the inputs
  required for that request.
- GitHub release/update checks and downloads; their controls are under Updates.
- The configured connection between the phone and your PC.

**Fonts are bundled.** The current Interstellar desktop and phone use local Space
Grotesk and IBM Plex Sans files under their SIL Open Font Licenses. The dashboard
does not fetch these fonts from Google Fonts at runtime. Repository provenance URLs
identify where bundled assets originated; they are not runtime font requests.

Source references: [storage and configuration](clipbot/config.py),
[local authentication](clipbot/auth.py), [secret storage](clipbot/secure.py),
[business/account boundaries](docs/BUSINESSES.md), and
[third-party notices](NOTICE.md).
