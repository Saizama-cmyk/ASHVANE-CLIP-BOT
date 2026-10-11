# Ashvane (phone)

A native app that runs your Ashvane content desk from your phone: today's production and post results,
source research, scripts and platform copy, streams, clip reviews, manual posting, settings and the log.
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

`App.js` handles the primary Desk, Research and Tools navigation. `Desk.js`, `Research.js` and `Remote.js`
provide the content desk screens. The app uses the web dashboard API and authenticates with a bearer
token from `/api/auth/login`. The local AI tools use a custom native module, so a native development
build is required instead of the standard Expo Go app. See [phone revamp verification](../docs/PHONE-REVAMP.md)
for bundle checks and the remaining device checks.
