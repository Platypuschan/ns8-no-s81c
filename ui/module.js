'use strict';
const match = location.pathname.match(/\/apps\/(no-s81c[1-9][0-9]*)\//);
if (match) document.getElementById('commands').textContent =
  `runagent -m ${match[1]} python3 -m localfonts.actions get-status </dev/null
` +
  `journalctl -u ${match[1]}-refresh.service -n 30 --no-pager`;
