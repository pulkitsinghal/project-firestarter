# Install, update, and rollback plan

Operations Floater has no network updater. Application replacement and snapshot
updates are explicit local operations with a retained rollback artifact.

## Release inputs

Keep these outside Git and set them to operator-controlled locations:

```bash
CANDIDATE_APP=...
INSTALLED_APP=...
BACKUP_APP=...
```

The candidate must be produced from the reviewed Firestarter commit with the
owner's bundle identifier and signing configuration. Do not place certificates,
profiles, account identifiers, runtime snapshots, or application backups in this
repository.

## Preflight

Before replacing an installed copy:

1. Record the candidate commit, bundle version, and short version.
2. Verify the signature and Gatekeeper assessment:

   ```bash
   codesign --verify --deep --strict --verbose=2 "$CANDIDATE_APP"
   spctl --assess --type execute --verbose=2 "$CANDIDATE_APP"
   ```

3. Confirm the built metadata contains the productivity category and expected
   encryption declaration.
4. Run the native unit/lifecycle tests and unsigned Release build from the same
   commit.
5. Export or retain the current local snapshot only in its private local
   storage. Never copy it into Git or a web publication directory.

Stop if identity, signature, metadata, or tests do not match the intended
release.

## First install

1. Quit any running copy.
2. Copy the candidate to `INSTALLED_APP` using a metadata-preserving local copy.
3. Launch it and verify one visible dashboard window, default frontmost state,
   unpin behavior, Command-W close, Dock reopen, and Reduce Motion.
   At the default size, confirm queue and supporting panels use two columns.
   Resize to the minimum and confirm they collapse to one column without
   clipping the guide summary or four queue counters.
4. Confirm each queue race shows a bounded progress chip, hover detail, and
   click-to-expand detail. Exercise last-active, completion, memory, CPU, and
   needs-attention sorting. Confirm an increased total-step count can move a
   chip backward and Reduce Motion replaces animation with a stable frame.
5. Choose **Import Local Snapshot…** only if a canonical `local` version `1.0`
   snapshot is ready. The app validates before writing and gives the stored file
   private permissions.
6. Confirm the header reports a locally verified snapshot rather than the
   generic sample.

## Update

1. Complete the preflight for the new candidate.
2. Quit the installed app.
3. Copy the existing installed app to `BACKUP_APP`.
4. Replace `INSTALLED_APP` with the candidate using a metadata-preserving copy.
5. Launch and repeat the lifecycle smoke checks.
6. Import the new local snapshot, if needed. A valid current snapshot is saved
   as the previous snapshot before the update is committed.
7. Leave `BACKUP_APP` and the previous snapshot intact through the acceptance
   period.

An invalid snapshot cannot replace the active snapshot. No selected source path
is retained, and no import data is transmitted.

## Rollback

Rollback triggers include failure to launch, signature or Gatekeeper rejection,
missing window lifecycle behavior, an unreadable compact layout, motion that
continues with Reduce Motion enabled, unreadable canonical state, or a material
display regression.

1. Quit the app.
2. Replace `INSTALLED_APP` with the verified `BACKUP_APP`.
3. Launch the restored app and verify its bundle version and lifecycle.
4. If only dashboard data regressed, choose **Restore Previous Snapshot**. The
   app validates the previous snapshot and swaps it with the current one, making
   the rollback itself reversible.
5. Re-run the focused native tests against the restored commit.

Do not delete the candidate, backup, or previous snapshot until the restored
state has passed the same acceptance checks.

## Cleanup

After acceptance:

- keep only the retention-approved application backup;
- remove rejected snapshot source files through the operator's normal secure
  local cleanup process;
- retain release commit, test output, and non-sensitive metadata as evidence;
  and
- never include runtime snapshot contents in bug reports or release notes.
