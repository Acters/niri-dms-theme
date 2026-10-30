# Niri + DMS glass theme kit

A session-aware theme bundle for Niri/Dux Shell: pale-blue light surfaces, black dark surfaces, translucent Qt widgets, balanced Kate editor themes, and an opt-in rounded Drawy profile.

**This repository does not migrate the running desktop automatically.** The existing setup is preserved. Installation stages only files in dedicated `niri-dms-theme` directories; activating the supplied service/config fragments is a separate, reviewed step. Source: [Acters/niri-dms-theme](https://github.com/Acters/niri-dms-theme).

## What's here

- [DMS palette](assets/dms/blue-black.json) and [Matugen Qt template](assets/qt/translucent.colors.in): 10% background alpha; normal text stays opaque.
- [Kate plugin](plugins/kate-balanced-glass/): balanced light/dark editor themes, roughly 64% text-row opacity, live switching and new/split views. It is inactive unless the `niri-dms-glass` marker **and** a Niri desktop context are present.
- [Drawy style adapter](plugins/drawy-glass-style/): 16px outer containers, stock Darkly rendering, and a narrowly version-guarded cleanup for Drawy 1.0.2's unused zoom-area hamburger.
- [Drawy wrapper](assets/drawy/drawy-glass): opt-in app profile with separate config/data/cache/state. Outside the marked Niri session it launches native Drawy without those overrides.
- [Session tooling](docs/session.md), process-local service drop-in templates, dry-run installation, private transaction backups, and drift-protected rollback.

No package patches, polling daemon, or full copies of personal desktop configuration are required.

## Preview the plan

Requirements: Python 3.10+, CMake, Ninja, a C++17 compiler, Qt6 Widgets/Test, KF6 TextEditor/CoreAddons/Config development files, Darkly, qtengine, Niri and DMS. Drawy is needed to use its optional launcher. See [tested versions and captured scope](docs/inventory.md).

```sh
./bin/themekit plan
./bin/themekit doctor
./bin/themekit build
./bin/themekit install             # dry-run, even after building
```

To test deployment without touching your home:

```sh
TEST_HOME=$(mktemp -d)
./bin/themekit install --home "$TEST_HOME" --mode light --apply
./bin/themekit rollback --home "$TEST_HOME" --apply
```

An explicit `--home` relocates **all** XDG roots and ignores ambient XDG paths. It is not a chroot: do not start real desktop services against a test installation.

When ready, `./bin/themekit install --apply` copies only owned resources under the selected XDG config/data roots. It does **not** enable units, edit main Niri/DMS preferences, import manager/D-Bus environment, restart services, enable Kate session plugins, replace desktop entries, or change drawing exports. Review [migration](docs/migration.md) before activation.

## Session isolation

The default is process-local `EnvironmentFile` settings on Niri and DMS. The generated Niri fragment supplies the same environment to compositor-spawned applications. Do not put profile-forcing variables into user-wide `environment.d` files.

The user manager and activation bus are shared by all sessions for one UID. An optional manager bridge snapshots/restores only its owned values; it cannot make concurrent DEs fully independent. It is not enabled by the default templates and never mutates D-Bus activation environment.

## Tests and rollback

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
./tools/test-plugins
```

`rollback` is dry-run unless `--apply` is supplied. It restores the latest transaction only if targets still match the installed hashes. It refuses drift, including a generated palette changed by DMS: do not force-delete newer data. Disable manually activated integrations before rolling back their resources. See [safety](docs/safety.md).

Original upstream theme credits/licenses are retained; [NOTICE](NOTICE.md) describes mixed asset provenance. Generated colors, binaries, user session files, screenshots, artwork, caches and transaction state are not source material.
