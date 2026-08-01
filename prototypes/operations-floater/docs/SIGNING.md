# Signing and notarization

Operations Floater ships as a Developer ID (direct) macOS app with the Hardened
Runtime. This document explains the distribution posture, what the entitlements
are, and exactly what the owner must do. It contains no credentials, team
identifiers, Apple IDs, or owner-specific values; every such value is supplied at
run time and never committed (firestarter's origin is public).

## Privacy-protected resources

The app uses two privacy-protected resources, both for the optional voice
conversation feature:

| Resource | Trigger in the app | Gate |
| --- | --- | --- |
| Microphone | Voice Conversation (`AVAudioEngine` / on-device speech) | Hardened Runtime entitlement + TCC (`NSMicrophoneUsageDescription`) |
| Speech Recognition | On-device transcription of voice turns | TCC (`NSSpeechRecognitionUsageDescription`) |

Both are requested only when the user explicitly starts Voice Conversation, and
transcripts are kept ephemeral. Everything else the app does — reading a local
snapshot, talking to the fixed loopback Router, and importing a user-selected
file — needs no special entitlement.

## Distribution posture: Developer ID direct + Hardened Runtime

**Adopted.** Distribute the app directly (Developer ID Application certificate +
notarization) with the Hardened Runtime enabled. Direct Developer ID
distribution is the target channel rather than the Mac App Store, so the App
Sandbox is not required and is left off; the Hardened Runtime still satisfies the
notarization requirement and constrains the process (code-injection,
unsigned-memory-execution, and library-validation protections all remain on).

> Note: the Mac App Store requires the App Sandbox. A future App Store variant
> would enable `com.apple.security.app-sandbox`; the microphone and Speech
> Recognition features both survive under the sandbox, so no capability is lost.

### Entitlements

`OperationsFloater.entitlements` is:

```xml
<key>com.apple.security.device.audio-input</key>
<true/>
```

That single key is the Hardened Runtime's microphone resource-access exception,
required before the mic can be used at all; TCC then prompts the user with the
`NSMicrophoneUsageDescription` string. Everything else needs no entitlement:

- **Speech Recognition** is TCC-gated by `NSSpeechRecognitionUsageDescription`;
  there is no Hardened Runtime entitlement for it.
- **Network** (`127.0.0.1:11500` loopback Router) and **user-selected files**
  (the Import Local Snapshot picker) are unrestricted without the sandbox.

`project.yml` sets `ENABLE_APP_SANDBOX: NO` and keeps
`ENABLE_HARDENED_RUNTIME: YES` so a regenerated Xcode project matches these
entitlements.

### One side effect: Application Support location

Running outside the sandbox keeps the app's storage at the standard
`~/Library/Application Support/` rather than a per-app container
(`~/Library/Containers/<bundle-id>/Data/Library/Application Support/`). The code
resolves this with
`FileManager.default.urls(for: .applicationSupportDirectory, ...)`
(`OperationsFloaterApp.swift`, `LocalSnapshotStore.swift`), so no code change is
needed; the process-scoped lease, saved snapshot, and receipts live at the
standard path. A migration is only relevant if a previously sandboxed build was
already installed with real data — not the case for a first release.

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
   app explicitly asks, **Microphone** and **Speech Recognition** — prompted the
   first time Voice Conversation starts.

   Grant these only to the signed, notarized, installed copy — never to a
   DerivedData product, SwiftPM executable, or other disposable build (each has
   a different code identity and would strand the grant on the next release).

## References

- [Apple: Hardened Runtime — Resource Access entitlements](https://developer.apple.com/documentation/security/hardened_runtime)
- [Apple: Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [Apple: Customizing the notarization workflow (notarytool)](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)
- [Apple: App Sandbox](https://developer.apple.com/documentation/security/app-sandbox)
