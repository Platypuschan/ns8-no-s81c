# 0.1.0-rc.2

This testing release replaces the command-instruction page with real **Cluster Admin module options**:

- Enable or disable local font delivery directly in the WebGUI.
- Display actual configuration and localization status, local font count, localized files and remaining external references.
- Refresh status and run an immediate check without a host shell.
- Show loading, failure, unknown and timeout states; prevent conflicting actions and clean up native task subscriptions on navigation.
- English and German interface using NS8's existing authenticated task bridge and host stylesheet. No external UI libraries or font CDN are added.

The native `refresh-fonts` action preserves the configured enabled/disabled state. Font localization, safe restore and the automatic path/timer checks remain. Browser regressions now gate package publication. Ordinary domain names in UI prose are not mistaken for downloadable font references.

## Important limits

This remains a rootfull Core-UI patch and an explicitly marked prerelease, not an official NS8 setting or stable certification. It needs Core 3.25.1 or later and may need adapting to future WebUI layouts. Initial missing-font downloads need trusted HTTPS access from the host. It does not eliminate unrelated external requests by other NS8 functions. Hard-refresh cached Cluster Admin CSS after initial application.

The [acceptance record](acceptance.md) distinguishes synthetic filesystem fixtures, simulated host-event-bus browser regressions and actual native-backend/browser tests. No full distro matrix, host-reboot, native backup/restore or production-soak coverage is claimed.

## Previous testing release

`0.1.0-rc.1` introduced the native rootfull module, journaled URL substitutions, SHA-checked font publication, oneshot/path/timer checks and reversible cleanup. That immutable release remains available; update an existing instance rather than adding another one.
