# Signing and notarization

Operations Floater ships as a Developer ID (direct) macOS app with the Hardened
Runtime and **without** the App Sandbox. This document explains why, what the
entitlements are, and exactly what the owner must do. It contains no
credentials, team identifiers, Apple IDs, or owner-specific values; every such
value is supplied at run time and never committed (firestarter's origin is
public).

## The sandbox vs. Input Monitoring conflict

The app needs three privacy-protected resources:

| Resource | Trigger in the app | Gate |
| --- | --- | --- |
| Microphone | Voice Conversation (`AVAudioEngine` / on-device speech) | Hardened Runtime entitlement + TCC (`NSMicrophoneUsageDescription`) |
| Speech Recognition | On-device transcription of voice turns | TCC (`NSSpeechRecognitionUsageDescription`) |
| Input Monitoring | Relative XY recorder — `CGRequestListenEventAccess()` / `CGPreflightListenEventAccess()` in `NeutralGeometryCapture.swift` | TCC (Privacy & Security -> Input Monitoring) |

The Relative XY recorder observes the **complete mouse, scroll, and key-code
stream of another application's selected window**. That is cross-process global
input monitoring. macOS deliberately does not allow a sandboxed process to
monitor input directed at other applications: the App Sandbox confines a process
to its own event stream, and `CGRequestListenEventAccess()` cannot grant a
sandboxed app system-wide Input Monitoring. So the two requirements are mutually
exclusive:

- **App Sandbox on** -> Input Monitoring of other apps' windows does not work,
  and the recorder — a headline feature — is dead.
- **Input Monitoring required** -> the app cannot be sandboxed.

The previously committed `OperationsFloater.entitlements` declared
`com.apple.security.app-sandbox = true` (and `project.yml` set
`ENABLE_APP_SANDBOX: YES`). That directly contradicts the recorder and the app's
own docs, which describe the main process as the sole Input Monitoring client.
The microphone sandbox entitlement (`com.apple.security.device.audio-input`) was
already present, but the sandbox itself was the blocker. This is the conflict
this change resolves.

> Note: because the App Store requires the App Sandbox, an app that keeps Input
> Monitoring **cannot** ship on the Mac App Store. Direct Developer ID
> distribution is the only channel that supports this feature.

## Recommendation: Developer ID direct + Hardened Runtime, no sandbox

**Adopted.** Distribute the app directly (Developer ID Application certificate +
notarization), enable the Hardened Runtime, and **do not** enable the App
Sandbox. This preserves the microphone, Speech Recognition, and Input Monitoring
features intact. The Hardened Runtime satisfies the notarization requirement and
still constrains the process (code-injection, unsigned-memory-execution, and
library-validation protections all remain on).

### Corrected entitlements

`OperationsFloater.entitlements` is now:

```xml
<key>com.apple.security.device.audio-input</key>
<true/>
```

That single key is the Hardened Runtime's microphone resource-access exception,
required before the mic can be used at all; TCC then prompts the user with the
`NSMicrophoneUsageDescription` string. Everything else needs no entitlement:

- **Speech Recognition** is TCC-gated by `NSSpeechRecognitionUsageDescription`;
  there is no Hardened Runtime entitlement for it.
- **Input Monitoring** is TCC-gated by `CGRequestListenEventAccess()`; it needs
  no entitlement and now works because the sandbox is gone.
- **Network** (`127.0.0.1:11500` loopback Router) and **user-selected files**
  (the Import Local Snapshot picker) are unrestricted without the sandbox, so
  the former `com.apple.security.network.client` and
  `com.apple.security.files.user-selected.read-write` keys were dropped as
  no-ops.

`project.yml` now sets `ENABLE_APP_SANDBOX: NO` and keeps
`ENABLE_HARDENED_RUNTIME: YES` so a regenerated Xcode project matches these
entitlements.

### One side effect: Application Support location

Leaving the sandbox moves the app's storage from the per-app container
(`~/Library/Containers/<bundle-id>/Data/Library/Application Support/`) to the
standard `~/Library/Application Support/`. The code resolves this with
`FileManager.default.urls(for: .applicationSupportDirectory, ...)`
(`OperationsFloaterApp.swift`, `LocalSnapshotStore.swift`), so no code change is
needed; the process-scoped lease, saved snapshot, and receipts simply live at
the standard path. A migration is only relevant if a previously sandboxed build
was already installed with real data — not the case for a first release.

## Tradeoff: the sandboxed alternative

If Mac App Store distribution or the stronger sandbox confinement were ever
required, the only way to stay sandboxed is to **drop Input Monitoring** —
remove the Relative XY recorder's cross-process event capture entirely (or
reduce it to events inside the app's own windows, which needs no special
permission). The sandboxed entitlements would then be:

```xml
<key>com.apple.security.app-sandbox</key><true/>
<key>com.apple.security.device.audio-input</key><true/>
<key>com.apple.security.network.client</key><true/>
<key>com.apple.security.files.user-selected.read-write</key><true/>
```

Microphone and Speech Recognition survive under the sandbox; only the recorder
is lost. Because the recorder is a defining capability of this app, the
non-sandboxed Developer ID path is recommended. Revisit only if the product
direction changes (e.g. an App Store build that deliberately omits the
recorder).

## OWNER checklist

These steps need the owner's Apple credentials and are **not** run by CI or by
any automation in this repo. Do them on the owner's signing machine.

1. **Obtain a Developer ID Application certificate.**
   In Xcode: Settings -> Accounts -> your Apple Developer team -> Manage
   Certificates -> "+" -> **Developer ID Application** (or create it in the
   Apple Developer portal and download it). Confirm it is installed in the login
   keychain:

   ```bash
   security find-identity -v -p codesigning | grep "Developer ID Application"
   ```

   Note the identity string, e.g. `Developer ID Application: Example Owner (TEAMID1234)`.

2. **Create the notary keychain profile** (store credentials once; the values
   never enter this repo). Preferred — an App Store Connect API key:

   ```bash
   xcrun notarytool store-credentials operations-floater-notary \
     --key "AuthKey_XXXXXXXXXX.p8" \
     --key-id "XXXXXXXXXX" \
     --issuer "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
   ```

   Alternative — Apple ID + app-specific password (create the password at
   appleid.apple.com -> Sign-In and Security -> App-Specific Passwords):

   ```bash
   xcrun notarytool store-credentials operations-floater-notary \
     --apple-id "you@example.com" \
     --team-id "TEAMID1234" \
     --password "abcd-efgh-ijkl-mnop"
   ```

3. **Build the .app on a disposable account / CI runner**, not the active
   profile (Xcode 26.5 runs `lsregister` during build/archive — see
   `docs/PERMISSION_AND_INSTALL_LIFECYCLE.md`). Set the owner's real bundle
   identifier and team at this stage; the checked-in `com.example.operationsfloater`
   is a disposable placeholder and must be overridden.

4. **Run the signing kit** against the built bundle:

   ```bash
   scripts/sign-and-notarize.sh \
     --app "/path/to/Operations Floater.app" \
     --identity "Developer ID Application: Example Owner (TEAMID1234)" \
     --notary-profile operations-floater-notary
   ```

   The script signs with the Hardened Runtime + these entitlements + a secure
   timestamp, submits to the notary service and waits, staples the ticket, and
   verifies with `spctl --assess`, `codesign --verify --deep --strict`, and
   `stapler validate`.

5. **(Optional) Run the identity preflight** before installing/updating the
   canonical copy:

   ```bash
   scripts/verify-permission-identity.sh \
     --candidate "/path/to/Operations Floater.app" \
     --expected-bundle-id "<owner-bundle-id>" \
     --expected-team-id "TEAMID1234"
   ```

6. **Grant TCC on first launch.** Launch the installed app and approve, when the
   app explicitly asks:
   - **Microphone** and **Speech Recognition** — prompted the first time Voice
     Conversation starts.
   - **Input Monitoring** — the app calls `CGRequestListenEventAccess()`, which
     opens Privacy & Security -> Input Monitoring; enable Operations Floater
     there, then retry recording. macOS cannot revoke this from inside the app;
     removal is done in System Settings.

   Grant these only to the signed, notarized, installed copy — never to a
   DerivedData product, SwiftPM executable, or other disposable build (each has
   a different code identity and would strand the grant on the next release).

## References

- [Apple: Hardened Runtime — Resource Access entitlements](https://developer.apple.com/documentation/security/hardened_runtime)
- [Apple: Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [Apple: Customizing the notarization workflow (notarytool)](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)
- [Apple: App Sandbox](https://developer.apple.com/documentation/security/app-sandbox)
- [Apple: CGRequestListenEventAccess()](https://developer.apple.com/documentation/coregraphics/cgrequestlisteneventaccess%28%29)
