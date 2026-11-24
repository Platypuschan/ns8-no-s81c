# Acceptance record

## Automated coverage

`python3 -W error::ResourceWarning -m unittest discover -s tests -v` and the same suite with `python3 -O`. Font fixtures are explicitly synthetic; these tests do not claim real browser font rendering.

The source-to-export package verifier inspects native rootfull/singleton labels, version/revision, the complete module/UI regular-file inventory, file hashes and executable native hooks. No test code or Python bytecode is shipped.

## Real-font isolated acceptance

Test platform: Rocky Linux 9.8, NS8 Core 3.25.1. An independent copy of the actual 422-file Cluster Admin tree was used, not a simplified CSS fixture.

- 240 unique WOFF/WOFF2 resources downloaded from IBM over certificate-verified HTTPS by the real downloader.
- Two CSS files localized, 240 unique local references each.
- A repeated reconcile made no changes.
- Restore returned the complete 422-file tree to the original per-file SHA256 inventory.
- Replacing `core.css` at the same pathname with fresh upstream content plus a marker was detected and repatched. Restore preserved that fresh content, rather than replaying an old backup.
- Final engine acceptance completed successfully in approximately 21 seconds.

## Native live acceptance

Completed on Rocky Linux 9.8 / Core 3.25.1:

- Native `cluster/add-module` installed the rootfull module. Installation read-back confirmed its node mapping and image digest.
- Native `cluster/remove-module` of the first owned test instance removed its agent/units/UI and restored all 422 original UI files to their pre-install SHA256 inventory. No local font publication directory remained.
- Reinstallation and a native in-place `cluster/update-module` passed. The instance UUID was unchanged across the update.
- Native `get-font-status`, inherited Core `get-status` (with JSON null input), and `get-configuration` returned valid results. Font status is deliberately separate from Core's service-status action.
- Native `configure-module` with `enabled:false` restored the original external references and removed the publication directory. Disabled status remained healthy. `enabled:true` reapplied all 240 fonts from cache.
- The hardened systemd oneshot exited successfully; path watcher and timer were active. Repeated reconciliation reported `changed:false`.
- A fresh Chromium context loaded the real HTTPS Cluster Admin login page: HTTP 200, IBM Plex Sans 400 loaded locally, zero requests to s81c.com, zero failed requests or page errors. Before installation, the same page made one real IBM font request.
- A second fresh context loaded the installed module's informational page and real host core stylesheet: Sans 300/400 and Mono 400 loaded locally; again no s81c.com requests/errors. The catalog screenshot is from this deployed page, without credentials or fabricated status.

Two integration defects found by the real native tests were fixed before publication and have regressions: the module name must not be mistaken for an external domain, and a custom font-status action must not append JSON to Core's inherited get-status response. The automated suite now contains 50 tests. Native acceptance applies to the tested active backend/UI payload; publication labels bind the final source revision separately.

The initial public version is a testing prerelease, not a stable release.

## Limits

No host reboot, full Debian/Rocky matrix, native backup/restore/migration, production soak or authenticated application-interaction test is claimed. The informational module page is not a live status dashboard. Non-recursive path watching has a 15-minute timer fallback. Readers of previously cached hashed CSS must hard-refresh after initial application. Concurrent root-level UI package writers are trusted administrative operations; inode/content guards narrow, but cannot eliminate, the final check-to-rename race.
