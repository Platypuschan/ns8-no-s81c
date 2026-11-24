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

Pending at this development snapshot. Publication is manual and must not be triggered until native installation/removal/update and a fresh-context browser font-load test have completed. The initial public version is a testing prerelease, not a stable release.

## Limits

No host reboot, full Debian/Rocky matrix, native backup/restore/migration, production soak or authenticated application-interaction test is claimed. The informational module page is not a live status dashboard. Non-recursive path watching has a 15-minute timer fallback. Readers of previously cached hashed CSS must hard-refresh after initial application. Concurrent root-level UI package writers are trusted administrative operations; inode/content guards narrow, but cannot eliminate, the final check-to-rename race.
