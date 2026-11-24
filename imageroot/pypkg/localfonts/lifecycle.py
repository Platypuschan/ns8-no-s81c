"""Instance-scoped native systemd integration, no running application container."""
from pathlib import Path
import re
import os
import subprocess
import tempfile

MARKER = '# Managed by ns8-local-fonts; instance='


def systemctl(*args):
    subprocess.run(['systemctl', *args], check=True, stdout=subprocess.DEVNULL, timeout=120)


def _owned(path, module):
    if path.is_symlink():
        return False
    return path.read_text().startswith(MARKER + module + '\n')


def install(module, state, unitdir=Path('/etc/systemd/system'), ctl=systemctl):
    texts = {name: MARKER + module + '\n' + text for name, text in units(module, state).items()}
    unitdir = Path(unitdir)
    for name in texts:
        path = unitdir / name
        if (path.exists() or path.is_symlink()) and not _owned(path, module):
            raise RuntimeError('refusing foreign systemd unit: ' + name)
    changed = False
    for name, text in texts.items():
        path = unitdir / name
        if path.exists() and path.read_text() == text:
            continue
        fd, tmp = tempfile.mkstemp(prefix='.local-fonts-', dir=unitdir)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), 0o644)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        changed = True
    if changed:
        ctl('daemon-reload')
    ctl('enable', '--now', module + '-refresh.path', module + '-refresh.timer')


def remove(module, state, unitdir=Path('/etc/systemd/system'), ctl=systemctl):
    names = units(module, state)
    for name in names:
        path = Path(unitdir) / name
        if (path.exists() or path.is_symlink()) and not _owned(path, module):
            raise RuntimeError('refusing foreign systemd unit: ' + name)
    present = {name for name in names if (Path(unitdir) / name).exists()}
    if not present:
        return
    watchers = [name for name in (module + '-refresh.path', module + '-refresh.timer') if name in present]
    if watchers:
        ctl('disable', '--now', *watchers)
    if module + '-refresh.service' in present:
        ctl('stop', module + '-refresh.service')
    for name in names:
        (Path(unitdir) / name).unlink(missing_ok=True)
    ctl('daemon-reload')

UI_ROOT = Path('/var/lib/nethserver/cluster/ui')

def units(module, state):
    if not re.fullmatch(r'no-s81c[1-9][0-9]*', module):
        raise ValueError('invalid module ID')
    state = Path(state)
    if str(state) != f'/var/lib/nethserver/{module}/state':
        raise ValueError('invalid state directory')
    stem = module + '-refresh'
    return {
        stem + '.service': (
            f'[Unit]\nDescription=Local IBM Plex fonts ({module})\nAfter=network-online.target\nWants=network-online.target\n'
            '\n[Service]\nType=oneshot\n'
            f'ExecStart=/usr/local/bin/runagent -m {module} python3 -m localfonts.actions reconcile\n'
            'TimeoutStartSec=30min\nUMask=0022\nNoNewPrivileges=yes\nPrivateTmp=yes\n'
            'ProtectSystem=strict\nProtectHome=yes\n'
            f'ReadWritePaths={UI_ROOT} {state}\n'
        ),
        stem + '.timer': (
            f'[Unit]\nDescription=Local fonts periodic fallback ({module})\n\n[Timer]\n'
            'OnBootSec=1min\nOnUnitInactiveSec=15min\nAccuracySec=30s\n'
            f'Unit={stem}.service\n\n[Install]\nWantedBy=timers.target\n'
        ),
        stem + '.path': (
            f'[Unit]\nDescription=Watch NS8 core UI changes ({module})\n\n[Path]\n'
            + ''.join(f'PathChanged={UI_ROOT}{suffix}\n' for suffix in ['', '/css', '/js', '/apps'])
            + f'Unit={stem}.service\n\n[Install]\nWantedBy=multi-user.target\n'
        ),
    }
