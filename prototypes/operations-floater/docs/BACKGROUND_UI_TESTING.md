# Low-disruption macOS UI testing

The least disruptive local workflow uses a spare macOS Desktop that the user
creates once and leaves available for dashboard testing. macOS does not expose
a supported API for silently creating or deleting Desktops, so that one-time
Mission Control step remains user-controlled.

## One-time setup

1. Open Mission Control with **Control-Up**.
2. Select **+** to create a spare Desktop.
3. Switch to the spare Desktop and launch the dashboard once in background test
   mode:

   ```bash
   open -g "/path/to/Operations Floater.app" \
     --args --background-ui-test
   ```

4. To launch from the normal work Desktop without switching first, use the
   dashboard's Dock item on the spare Desktop:
   **Options → Assign To → This Desktop**. Leave the spare Desktop available.
5. Return to the normal work Desktop.

The Dock assignment is required for automatic routing when launch begins on a
different Desktop. It is keyed to the built app's bundle identifier and stored
as macOS user state, not as a repository or application setting. A newly built
candidate with a different bundle identifier needs its own one-time assignment.

## Test-mode contract

`--background-ui-test` changes presentation behavior only:

- **Keep in front** starts off and the window uses normal level;
- the window does not opt into **Join All Spaces**;
- launch does not activate Operations Floater;
- launch does not call force-front window ordering; and
- snapshots, validation, privacy boundaries, chat defaults, and schema `1.0`
  remain unchanged.

Normal launches intentionally retain foreground activation. Every launch is
unpinned by default and uses one Space.

```text
User creates spare Desktop once
              |
              v
Assign app to that Desktop (optional but recommended)
              |
              v
open -g ... --args --background-ui-test
              |
              +--> normal-level window on one Desktop
              +--> foreground app remains unchanged
              +--> pointer is not moved by the launch command
```

## Limits and fallbacks

- The initial Desktop creation and first Dock assignment are visible user
  actions. Later assigned launches can begin from the work Desktop.
- macOS may animate a Desktop switch; Reduce Motion can reduce but not eliminate
  every transition.
- A single physical display cannot show two Desktops simultaneously.
- If assignment is unavailable or unreliable, switch to the spare Desktop
  before launching, then return to the work Desktop.
- Automated structural checks should prefer background accessibility
  inspection. Pixel-regression work that must be completely isolated belongs
  on a secondary display, a separate GUI login session, or a virtual machine.
- This mode reduces interruption; it does not claim that every macOS release,
  window manager, or third-party utility will preserve focus identically.

Before each run, verify that no old Operations Floater process remains. Launch
without `open -n`; a repeated LaunchServices open should route to the existing
process, and the app also rejects a duplicate same-bundle process before
creating a second dashboard window. Record the exact test executable path and
PID, and terminate only that exact test instance during cleanup.
