# Working on this theme

- Keep the user workflow to install, preview and restore. Don't add a staging framework or make users export environment boilerplate.
- Install and restore are explicit actions; --dry-run is available. Never run a live install while developing/testing unless directly requested. Use temporary homes for tests.
- Keep activation process-local to Niri/DMS. No recurring manager bridge, polling daemon or package patches.
- Preserve unrelated app settings, session/document state and drawings. Restore only this theme's owned changes; never delete runtime artwork or app-data directories.
- Keep the common Qt material and Kate switching profile/session-gated. Keep Drawy's canvas/config/data isolated and document its export-alpha behavior. Do not decorate editor/canvas content or paint over native foreground text.
- Build output, generated palettes, credentials, private backups, caches, artwork and session snapshots stay out of Git.
- Retain upstream credits/licenses. Do not commit or push without a direct request.
