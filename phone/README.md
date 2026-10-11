# Ashvane (phone)

A native app that runs your Ashvane content desk from your phone: today's production and post results,
source research, scripts and platform copy, streams, clip reviews, manual posting, settings and the log.
Use the business switcher beneath Ashvane to open **Surge**, **Hollow**, **Resonance** or **Social Studio**.
Surge owns streamer clips and research. Hollow owns scary stories and its separate publishing accounts.
Resonance creates local music, auditions sources and prepares editable REAPER sessions. Social Studio
keeps each client’s brand rules, styles, drafts, calendar, reference assets and public profile links.
Each business remembers its last screen. Switching workspaces never starts an engine: use the
selected business’s independent Start / Stop control. Assistant and Code remain shared optional Tools.
It talks to Ashvane on your PC over your own Wi-Fi or configured Tailscale connection using your profile sign-in.

## Get the file

Every build is published as a release, and one URL always points at the newest one:

**https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/Ashvane.ipa**

Android: **https://github.com/Saizama-cmyk/ASHVANE-CLIP-BOT/releases/download/phone-latest/Ashvane.apk**.
Each release also includes `SHA256SUMS.txt`, the iPhone package and permissions reports, and the
sideload source. Check the release notes for the built source commit and any Android build failure.

It is unsigned on purpose — your sideloader signs it with your own Apple ID, which is what makes
sideloading work without a paid developer account.

## Install it (pick the tool you already use)

| You are on | Tool | Notes |
|---|---|---|
| Windows | [AltStore](https://altstore.io) (AltServer) | Auto-refreshes over Wi-Fi every 7 days |
| Windows | [Sideloadly](https://sideloadly.io) | Simple drag-and-drop; re-install by hand |
| macOS | AltStore or Sideloadly | Same as above |
| Linux | [SideStore](https://sidestore.io) | Pairs on-device; no desktop server needed |
| Any | [Feather](https://github.com/khcrysalis/Feather) (on-device) | Installs and updates from a source |
| Jailbroken / TrollStore | ESign, TrollStore | Permanent signing, no 7-day limit |

With a free Apple ID any sideloaded app stops working after 7 days until it is re-signed. AltStore
and SideStore do that automatically in the background; the others need a re-install. That is
Apple's rule, not this app's.

## Live updates, like the desktop app

Add this **source** once and new builds appear as updates in the app list:

```
https://raw.githubusercontent.com/Saizama-cmyk/ASHVANE-CLIP-BOT/main/docs/sideload.json
```

Works in AltStore, SideStore, Feather and anything else that reads the standard source format.
For tools without sources (Sideloadly, ESign), re-download the `phone-latest` link above — it
always serves the newest build.

## Connect it

1. On the PC: **Settings → Dashboard → Phone remote**, then restart Ashvane.
2. The Live desk grows a **Phone remote** button showing the address, e.g. `192.168.0.72:8787`.
3. In the app, type that address and your profile password. The session token is kept in the iOS
   keychain; the password is never stored.

## If it cannot connect

- Phone and PC must be on the same network (not guest Wi-Fi, not cellular).
- Ashvane must be running with Phone remote switched on.
- Allow Ashvane through the firewall on private networks when Windows asks.
- Your PC's address can change when the router reissues it — retype it, or give the PC a reserved
  address in your router.

## Building it yourself

Apple's toolchain only runs on macOS, so the repo builds it on a free GitHub macOS runner:
Actions → **Phone app (.ipa + .apk)** → Run workflow. This existing workflow builds both platforms and
publishes installation files to the `phone-latest` release. An Expo export alone is not an installation file.

Locally:

```bash
cd phone
npm ci
npx expo run:android  # requires Android SDK, a full JDK and an emulator or connected device
```

`App.js` handles the four-business switcher, independent runtime controls and shared Tools navigation. `Stories.js` provides the
story composer, manuscript and scene controls, private review, final video preview and independent
publishing controls. `StoryAccounts.js` edits only story credentials, preserves blank secrets, and
starts OAuth in the PC browser; the returned sign-in link and pasted return URL provide phone recovery.
Stories Settings edits only the Stories configuration. Clip state/research polling stops in Stories.
`Portal.js` transitions the live screen through a central black hole when crossing
between Clips and Stories, with a short opacity transition when reduced motion is enabled.

The phone downloads a final story preview with its bearer token into a temporary private cache;
the token never goes into a media URL. Leaving the preview removes that cache. Production and
publishing continue on the PC when the phone sleeps. Story polling stops while the app is locked,
in the background, or on another tab.

`Desk.js`, `Research.js` and `Remote.js`
provide the content desk screens. The app uses the web dashboard API and authenticates with a bearer
token from `/api/auth/login`. The local AI tools use a custom native module, so a native development
build is required instead of the standard Expo Go app. See [phone revamp verification](../docs/PHONE-REVAMP.md)
for bundle checks and the remaining device checks.

## Music and social workspaces

`Music.js` uses the authenticated `/api/music` bridge. Generation, producer and REAPER export jobs
can be cancelled separately. Production notes remain editable; opening REAPER explicitly opens it
on the PC. A rendered version still needs your audition. Readiness comes from the local tools,
not simply from REAPER being installed. Music Settings edits only the music configuration.

`Social.js` loads each client’s own rules, styles, posts, public profiles and registered assets.
QuirkyCMD is seeded by the PC when its recovered project context exists. Archive assets stay labelled
as historical references. Calendar dates are planning records; publishing remains manual.
The phone does not connect Social Studio to Surge or Hollow accounts. Social Settings edits only
the social configuration. Unsaved edits are guarded when leaving a workspace or changing clients.

`BusinessMedia.js` fetches private audio, images and videos with a bearer header. Native previews
use temporary private cache files, and browser previews use temporary object URLs; leaving a preview
cleans up the local copy. No session token is put in a media URL.

Isolated verification: export with `npx expo export --platform all --output-dir ../artifacts/phone-four-business-export`,
serve that directory at `127.0.0.1:8140`, then run `node scripts/verify_phone_workspaces.cjs` from the repo root.
The verifier uses fixture endpoints only and covers both 320px and 390px layouts, runtime isolation,
music transactions, client-scoped social editing and authenticated media. Native release version
1.0.24 is assigned by the existing release workflow when the integrated change is published.
