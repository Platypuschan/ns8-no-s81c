# NS8 No s81c

Small native **rootfull** NS8 module that self-hosts the IBM Plex font files referenced by Cluster Admin. No application container, network listener, reverse-proxy change or extra port. The native NS8 module agent remains part of NS8 management.

## Use in Cluster Admin

Open **Applications → No s81c → Settings**. No host shell is required for normal operation.

- **Local fonts enabled:** enable or disable localization and apply the change. Disabling restores the module-owned original URLs; enabling reapplies the local copies.
- **Status:** read the actual configuration, localization health, number of local font files, localized files and remaining external references. A failed read is shown as unknown/error, not as a stale green success.
- **Refresh:** reload the current status without changing configuration.
- **Check now:** run the normal localization check immediately. This does not enable a disabled module.

The page is available in English and German and uses the existing authenticated NS8 session. Without the Cluster Admin host context, controls remain unavailable rather than pretending that settings were saved. Running actions disable conflicting controls; errors and timeouts are visible in the page.

## Scope

- Rewrite only supported IBM Plex font URLs in existing CSS/JS assets.
- Keep the existing font family, weights and languages; do not replace them with fallback fonts.
- Cache downloads in the instance state and publish them below `/cluster-admin/local-fonts/`.
- Run a hardened oneshot systemd service on relevant top-level UI changes, at boot and every 15 minutes. The watcher is not recursive: nested module asset changes are repaired by the timer.
- Use native `get-font-status`, `get-configuration`, `configure-module` and `refresh-fonts` actions. Core's inherited service `get-status` action is preserved.
- On deactivation/removal, reverse only owned URL substitutions, not an outdated backup of the whole UI. Other edits and updated UI files are preserved.

This is a **Core UI patch**, not an official Core configuration switch. A future Core layout or font URL format can need a module adaptation. Unsupported URLs are reported instead of blindly rewritten. This does not eliminate unrelated external requests from other NS8 features. Hard-refresh previously cached Cluster Admin CSS after first application.

## Installation and updates

For an **already installed instance**, use the update offered by Software Center; do not install another copy. This module permits at most one instance per node and needs Core 3.25.1 or later.

For a fresh installation, enable the [Platypuschan NS8 catalog](https://platypuschan.github.io/ns8-modules/ns8/updates/) and install **No s81c (local fonts)** on the intended node. RC builds are explicitly marked as testing versions. The patch engine also refuses a publication directory owned by another instance.

Normal removal through Cluster Admin invokes the native destructor and reverses owned substitutions. Do **not** force-remove a failed destructor or manually delete the state: its ownership journal is needed for safe cleanup. Investigate the reported error first. No host reboot is necessary.

## Initial downloads

The host needs trusted HTTPS access to `https://1.www.s81c.com/` when a referenced font is missing. Fonts are downloaded from IBM at runtime, not redistributed in the module image. Failed downloads leave the corresponding original external reference intact until a later successful retry. Cached fonts can be reused after UI updates. Font files retain their upstream licensing; [IBM Plex uses the SIL Open Font License](https://github.com/IBM/plex/blob/master/LICENSE.txt).

## Development and verification

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
NS8_CORE_CSS=/path/to/verified/core.css node tests/ui-browser.cjs
podman build --no-cache --build-arg REVISION="$(git rev-parse HEAD)" \
  -t localhost/ns8/no-s81c:0.1.0-rc.2 .
python3 scripts/verify-package.py localhost/ns8/no-s81c:0.1.0-rc.2
```

Browser tests need Playwright 1.64.1 and Chromium. CI extracts the host stylesheet from a digest-pinned official Core image and gates package publication on the browser suite. API/event-bus fixtures are explicitly distinguished from real backend acceptance in [the acceptance record](docs/acceptance.md).

Manual publication reuses the exact tested OCI archive without rebuilding. Published version tags are not overwritten. The [release notes](docs/release-notes.md) describe the current testing release.

## License

Module source: GPL-3.0-or-later. No IBM font binaries are included in the source/module image.
