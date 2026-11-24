"""Native NS8 action entrypoint; no public service, credentials or extra ports."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
from . import lifecycle


def write_config(state, enabled):
    fd, tmp = tempfile.mkstemp(prefix='.config-', dir=state)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'enabled':enabled}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, state / 'config.json')
        directory = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Controller:
    def __init__(self, engine, module, state, life=lifecycle):
        self.engine, self.module, self.state, self.life = engine, module, Path(state), life

    def enabled(self):
        try:
            cfg = json.loads((self.state / 'config.json').read_text())
        except FileNotFoundError:
            return True
        if set(cfg) != {'enabled'} or type(cfg['enabled']) is not bool:
            raise ValueError('invalid local-fonts configuration')
        return cfg['enabled']

    def execute(self, action, request):
        if action == 'get-configuration':
            return {'enabled':self.enabled()}
        if action == 'get-status':
            return dict(self.engine.status(), enabled=self.enabled())
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.state / '.controller.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if action == 'configure-module':
                if set(request) != {'enabled'} or type(request['enabled']) is not bool:
                    raise ValueError('enabled must be an explicit boolean')
                # Persist off first: a failed restore must never re-enable patching.
                if not request['enabled']:
                    write_config(self.state, False)
                    result = self.engine.disable()
                else:
                    write_config(self.state, True)
                    self.engine.enable()
                    result = self.engine.reconcile()
                return dict(result, enabled=self.enabled())
            if action in ('create-module', 'update-module', 'restore-module'):
                if not (self.state / 'config.json').exists():
                    write_config(self.state, True)
                self.life.install(self.module, self.state)
                if self.enabled():
                    self.engine.enable()
                    result = self.engine.reconcile()
                else:
                    result = self.engine.disable()
                return dict(result, enabled=self.enabled())
            if action == 'destroy-module':
                write_config(self.state, False)
                self.life.remove(self.module, self.state)
                return self.engine.disable()
            if action == 'reconcile':
                return dict(self.engine.reconcile() if self.enabled() else self.engine.status(), enabled=self.enabled())
            raise ValueError('unsupported local-fonts action')


def main():
    from .engine import Engine
    module = os.environ['MODULE_ID']
    state = Path(os.environ['AGENT_STATE_DIR'])
    # Validate privileged paths before constructing the engine.
    lifecycle.units(module, state)
    action = sys.argv[1]
    request = json.loads(sys.stdin.read() or '{}') if action not in ('reconcile','update-module') else {}
    controller = Controller(Engine(lifecycle.UI_ROOT, state), module, state)
    try:
        result = controller.execute(action, request)
        json.dump(result, sys.stdout)
        sys.stdout.write('\n')
        if result.get('ok') is False or result.get('errors'):
            return 1
        return 0
    except Exception as exc:
        # Bounded error text; module has no secret inputs or outbound credentials.
        json.dump({'error':type(exc).__name__, 'message':str(exc)[:400]}, sys.stdout)
        sys.stdout.write('\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
