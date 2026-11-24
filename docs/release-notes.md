# 0.1.0-rc.1

Initial testing release of **No s81c (local fonts)** for NethServer 8 Core 3.25.1 or later.

- Native rootfull module, at most one instance per node; no application container, listener or port allocation.
- Local cache and HTTPS delivery of IBM Plex WOFF/WOFF2 fonts used by Cluster Admin; initial missing-font downloads are performed by the host, not the browser.
- Instance-scoped oneshot service, path watcher, boot check and 15-minute fallback timer.
- Atomic, journaled URL substitutions in CSS/JS, preserving file metadata and refusing unsupported URLs, unsafe paths, foreign resource ownership and invalid fonts.
- SHA-checked publication/status, safe reapplication after UI updates, native enable/disable/status and cleanup of owned substitutions on removal.
- Small informational module page with native operation commands. No live GUI dashboard is claimed.

This is a Core UI patch, not an official NS8 setting. Clear the browser cache after first application. Unsupported future UI layouts are reported rather than blindly rewritten. Initial downloads need Internet access. Other NS8 features may still make external requests. Read the README before installing.

Automated filesystem and controller tests use explicit synthetic font fixtures. A separate real-font acceptance used an isolated copy of a Rocky Linux 9.8 / Core 3.25.1 WebUI: 240 real WOFF/WOFF2 files over trusted HTTPS, two patched CSS files, exact 422-file restore roundtrip and a same-path UI replacement/restore test. See `docs/acceptance.md` for the final live-install checks and their limits.

This release is a prerelease/testing build. No claim of full Debian/Rocky matrix, host-reboot, native backup/restore or production-soak acceptance.
