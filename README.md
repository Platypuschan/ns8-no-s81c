# NS8 No s81c

Small native **rootfull** NS8 module that self-hosts the IBM Plex font files referenced by Cluster Admin. No application container, network listener, reverse-proxy change or extra port. The native NS8 module agent remains part of NS8 management.

## Scope

- Rewrite only supported IBM Plex font URLs in existing CSS/JS assets.
- Keep the existing font family, weights and languages; do not replace them with fallback fonts.
- Cache downloads in the instance state and publish them below `/cluster-admin/local-fonts/`.
- Run a hardened oneshot systemd service on relevant top-level UI changes, at boot and every 15 minutes. The watcher is not recursive: module asset changes not visible at a watched directory are repaired by the timer.
- Expose native `get-font-status`, `get-configuration` and `configure-module` actions. The small module UI is an informational page, not a live dashboard.
- Deactivation/removal restores only owned URL substitutions, not an outdated backup of the whole UI. Other edits and updated UI files must be preserved.

This is a **Core UI patch**, not an official Core configuration switch. A future Core layout or font URL format can need a module adaptation. Unknown URLs must be reported instead of blindly rewritten. This does not eliminate unrelated external requests from other NS8 features.

## Initial downloads

The host needs working trusted HTTPS access to `https://1.www.s81c.com/` when a new referenced font is missing. Fonts are downloaded from IBM at runtime, not redistributed in the module image. Failed downloads must not produce broken rewritten CSS; the old external reference remains until a later successful retry. Cached resources allow later reapplication without re-downloading the same fonts. Font files retain their upstream licensing; IBM Plex is distributed under SIL Open Font License: <https://github.com/IBM/plex/blob/master/LICENSE.txt>.

## Build (no publication)

```sh
python3 -m unittest discover -s tests -v
podman build --no-cache --build-arg REVISION="$(git rev-parse HEAD)" \
  -t ghcr.io/platypuschan/no-s81c:0.1.0-rc.1 .
podman save --format oci-archive -o local-fonts.oci.tar \
  ghcr.io/platypuschan/no-s81c:0.1.0-rc.1
```

Transfer the archive securely to the intended node and load it with `podman load -i local-fonts.oci.tar`. Install with the native cluster `add-module` action and explicit JSON `{"image":"ghcr.io/platypuschan/no-s81c:0.1.0-rc.1","node":1}` **only if no existing instance exists**. For an existing instance use native `update-module`, not a second `add-module`. Confirm the node identity independently: a hostname such as `node2` is not its NS8 numeric ID. The local archive is not a publicly pullable registry release.

Labels declare max one instance per node and minimum Core 3.25.1. The patch engine also refuses a foreign local-fonts publication owner. Repository: https://github.com/Platypuschan/ns8-no-s81c. Catalog: https://platypuschan.github.io/ns8-modules/ns8/updates/. Prereleases are explicitly marked as testing.

## Operations

Substitute the actual native instance ID (example `no-s81c1`):

```sh
runagent -m no-s81c1 python3 -m localfonts.actions get-font-status </dev/null
runagent -m no-s81c1 python3 -m localfonts.actions get-configuration </dev/null
runagent -m no-s81c1 python3 -m localfonts.actions reconcile
journalctl -u no-s81c1-refresh.service -n 50 --no-pager
systemctl status no-s81c1-refresh.path no-s81c1-refresh.timer
```

Use the native `configure-module` action with explicit `{"enabled":false}` to stop rewriting and restore owned references, or `{"enabled":true}` to reapply. The equivalent host invocation is:

```sh
printf '%s\n' '{"enabled":false}' | \
  runagent -m no-s81c1 python3 -m localfonts.actions configure-module
```

Normal native removal calls `destroy-module` before erasing the module. Do **not** force-remove a failed destructor or manually delete the state: its ownership journal is needed for safe cleanup. Investigate reported errors first. No host reboot is necessary.

## Verification

Keep fixture tests distinct from real acceptance. Acceptance should include actual NS8 install/status/update/remove, a second idempotent reconcile, simulated UI replacement in an isolated copy, deactivation/reactivation and browser requests from a fresh browser context. A cached browser context is not proof of no external font loads. Verify HTTPS delivery of local font bytes and font loading, not just the absence of strings in source CSS.

## License

Module source: GPL-3.0-or-later. No IBM font binaries are included in the source/module image.
