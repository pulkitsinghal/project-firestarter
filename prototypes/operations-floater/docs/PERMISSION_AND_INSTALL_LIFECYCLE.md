# Permission and install lifecycle

## Why routine rebuilds lose Input Monitoring

macOS grants privacy-protected resources to a code identity, not merely to an
application name or icon. Apple documents that the designated requirement (DR)
is the rule macOS uses to recognize later versions of signed code. An unsigned
app has no DR, while an ad-hoc signature is tied to that specific version of the
code. Replacing an installed ad-hoc build can therefore present a new identity
to TCC.

The checked-in `com.example.operationsfloater` identifier and unsigned or
ad-hoc builds are disposable source-validation artifacts. They are never
install candidates and must not be launched as the permission-bearing copy.

## Stable release identity

An installable candidate preserves all of these across releases:

1. one owner-controlled, non-placeholder bundle identifier;
2. one owner-controlled Apple signing team;
3. an Xcode-produced Developer ID Application DR based on team and identifier,
   not one executable CDHash;
4. the canonical `/Applications/Operations Floater.app` path; and
5. the main application executable as the sole Input Monitoring client.

Developer ID Application plus notarization is the distribution target. Signing,
notarization, installation, and the first owner-controlled TCC grant are
separate owner gates. A future Mac App Store variant needs Apple's mutually
compatible-DR procedure; do not hand-author a custom DR.

## Build and install separation

Routine validation on the active macOS account uses SwiftPM plus synthetic
fixture tests. It does not create or launch an application bundle.

Battle testing with Xcode 26.5 found that both `xcodebuild build` and
`xcodebuild archive` invoke `lsregister` for the generated app. Supplying
`REGISTER_WITH_LAUNCH_SERVICES=NO` did not suppress that phase. Do not treat
that build setting as an isolation boundary. App-bundle compilation must run on
a disposable macOS account or CI runner whose Launch Services database is not
the owner's active application profile.

Only an owner-gated release job may inject the bundle identifier and team,
sign, notarize, pass the read-only identity gate, and produce an install
candidate. Only a separately gated install may replace the canonical app.

For first install, run the identity gate without `--installed`. For updates,
provide both apps; the gate verifies the signatures and Team Identifier, rejects
ad-hoc/CDHash-only identity and unexpected helpers, and proves the installed and
candidate DRs mutually compatible.

## Helper lifecycle

Operations Floater currently embeds no LaunchAgent, Login Item, XPC service,
daemon, privileged helper, or updater. Selected-window monitoring belongs to
the main application process, so TCC has one client identity.

A future helper requires a separate bundle identifier, stable signature, DR,
`SMAppService` registration plan, rollback path, permission analysis, and owner
gate. The identity preflight rejects helper payloads until that lifecycle is
reviewed. Stale helper inspection/removal is also an owner-controlled
maintenance action.

## Runtime invariants

- Launch Services routes a repeated open to the running app. A process-scoped
  advisory lock prevents direct executable launches or `open -n` from starting
  a second recorder host.
- The retained controller owns one dashboard window per process.
- The window is managed on one Space and never joins all Spaces.
- **Give floor** grants the module floor, starts selected-window recording, and
  then starts voice. Recording failure revokes recorder state and floor. Voice
  failure stops voice, removes the event monitor, and revokes recorder state and
  floor. Only complete activation remains live.
- Returning to the dashboard, collapsing chat, or clearing the session stops
  voice and clears ephemeral recorder state.

## Safe validation

Automated validation on the active account uses only synthetic window,
event-monitor, voice, signing, Gatekeeper, plist, and DR fixtures. It must not
call `CGRequestListenEventAccess`, create or register an app bundle, launch a
candidate, mutate TCC or System Settings, install over the active app, sign,
notarize, publish, or release.

References:

- [Apple TN3127: Inside Code Signing — Requirements](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements)
- [Apple: Creating distribution-signed code for macOS](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac)
- [Apple: CGPreflightListenEventAccess](https://developer.apple.com/documentation/coregraphics/cgpreflightlisteneventaccess%28%29)
