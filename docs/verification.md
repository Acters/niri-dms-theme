# Verification record

Local checks on the captured 2026-10-29 stack:

- 63 Python unit/integration tests passed: dry-run purity, explicit-home XDG relocation, backups/permissions, rollback/drift/interruption recovery, traversal/symlink rejection, environment parsing, fake-manager ownership/restoration/failure cases, bootstrap palette roles, installed helper imports, and the Drawy wrapper's outside-session fallback.
- Both native plugin projects built with the tested Qt/KF6 SDK.
- Kate QtTest: 4 checks passed, including existing/new/split/multiple-window switching and inactive behavior in COSMIC or an unmarked Niri context.
- Drawy style checks passed: rounded Frame metric, ordinary margins unchanged, orphan hidden only for the targeted version, real/managed/connected controls retained, future-version control left alone.
- A full resource deployment and rollback ran inside a temporary home, not the real home. Native tests used offscreen Qt and installed test resources.

The GitHub check runs only the portable Python suite. Native plugin tests require the appropriate desktop SDK and can be run with `tools/test-plugins`.

Not performed by repository creation: live hook migration, replacing the currently installed helpers, service restarts, global environment changes, compositor/app restarts, logout/relogin into another DE, or GitHub publication. The current working desktop still uses its existing configuration; see the migration checklist for known overlap.

A source build/test passing is not proof of an arbitrary distribution/version combination or complete concurrent graphical-session isolation. The profile deliberately does not manage GPU bridges, display affinity, a separate user bus, or an entire DE's configuration.
