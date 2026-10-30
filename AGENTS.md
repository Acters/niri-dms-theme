# Working on this theme kit

- Do not change the live desktop while editing or testing this repository unless directly requested.
- Installation and rollback are dry-run by default; test writes with an explicit temporary `--home` outside the checkout.
- Keep default activation process-local. Manager environment is shared; the optional bridge must remain opt-in and ownership-aware. Never manipulate a real user manager in tests.
- Preserve app preferences, session contents, drawings and other desktop sessions. Do not copy whole config directories or Kate session files into Git.
- Keep Kate switching gated by both the profile marker and Niri desktop context. Drawy changes must stay per-app and document export-alpha effects.
- No package patches, polling daemon or additional always-running helper for these features.
- Build outputs, generated palettes, caches, private paths, transaction backups and screenshots/artwork are not source assets.
- Retain upstream theme licenses/credits. Do not commit, publish, push, or configure a GitHub remote without a direct request.
