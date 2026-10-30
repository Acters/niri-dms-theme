# Deployment safety

- `plan`, `doctor`, plain `install` and plain `rollback` do not write target files or call services.
- `build` executes this repository's CMake projects and writes only inside its ignored build directory. Inspect source before building any repository.
- `install --apply` writes only dedicated profile config/data paths declared by the manifest. It does not activate units or change application/session preferences.
- Explicit `--home` ignores ambient XDG roots. Use a temporary home outside this repo for tests.
- Sources cannot escape the checkout; destinations cannot escape the owned profile prefixes. Symlink ancestors, traversal and non-regular targets are rejected.
- Writes use temporary files and atomic replacement. Original contents/modes are journaled before deployment; interrupted transactions block a new install until recovery/rollback.
- Backups are private user state, not Git content. The ledger contains original file bytes and absolute paths; treat it as personal data.
- Rollback preflights hashes and modes before changing files. It refuses manual edits and normal runtime-generated drift rather than silently overwriting them. The latest transaction is rolled back, not every historical update at once.
- A normal DMS regeneration can change the generated palette after installation. Review that drift before rollback; the runtime output is reproducible from the source theme/template, but the tool intentionally does not guess whether a changed file is disposable.
- Disable/review manually activated drop-ins, includes and desktop entries before removing their referenced resources. Missing EnvironmentFile is tolerated by the supplied templates, but optional legacy manager hooks require explicit cleanup while the helper still exists.
- Restart apps after replacing a loaded plugin binary. Installation uses replacement rather than truncating a mapped library, but a running process keeps its already-loaded code.
- Run deployment/rollback operations serially. Session-manager ownership operations have an advisory lock; the initial deployment CLI is a single-operator tool, not a concurrent package manager.
- Do not commit generated colors, binaries, screenshots with private content, drawings, autosaves, credentials, open-document lists, caches or transaction ledgers.

The optional manager bridge is explicitly separate from normal installation. Its ownership checks do not turn a UID-wide manager or D-Bus into a per-DE environment namespace. Process-local activation is the recommended design.
