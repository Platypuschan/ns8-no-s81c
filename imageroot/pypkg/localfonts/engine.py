"""Local IBM Plex font patch engine (stdlib only).

Engine(ui_root, state_root, downloader=None)
  reconcile() -> status dict  (download/publish fonts, patch CSS/JS, idempotent)
  restore()   -> status dict  (reverse module-owned local URLs; keep reconcile enabled)
  disable()   -> status dict  (restore + persistent disabled flag; reconcile becomes no-op)
  enable()    -> status dict  (clear disabled flag; does not patch)
  status()    -> status dict  (read-only scan, no network, no writes)
Status: {"ok","changed","disabled","files":{relpath:{"state",...}},"fonts":{"owned"},"errors":[...]}
File states: pending, patched, unknown_ref, missing_fonts, error, foreign_local.
Raises EngineError only for unusable roots / corrupt state.
"""
import errno, fcntl, hashlib, json, os, re, stat, time, urllib.request

HOST = "https://1.www.s81c.com/"
LOCAL_PREFIX = "/cluster-admin/local-fonts/"
FONTS_DIRNAME = "local-fonts"
MARKER = ".localfonts-owner"
MAX_FONT = 5 * 1024 * 1024
MAX_TEXT = 16 * 1024 * 1024
TOKEN = r"[^\s\"'()<>\\,;]*"
REL_RE = re.compile(r"^common/carbon/plex/fonts/(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*\.woff2?$")
REMOTE_RE = re.compile(re.escape(HOST) + TOKEN)
LOCAL_RE = re.compile(r"(?<![\w./:%@-])" + re.escape(LOCAL_PREFIX) + TOKEN)


class EngineError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _default_download(url):
    if not url.startswith("https://"):
        raise EngineError("non-https url")
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "ns8-localfonts/1"})
    deadline = time.monotonic() + 30
    buf = b""
    with opener.open(req, timeout=15) as r:
        if r.status != 200:
            raise EngineError("http %s" % r.status)
        while len(buf) <= MAX_FONT:
            if time.monotonic() > deadline:
                raise EngineError("download timeout")
            chunk = r.read(65536)
            if not chunk:
                break
            buf += chunk
    return buf


def _valid_rel(rel):
    return bool(REL_RE.match(rel)) and ".." not in rel


def _check_font(data):
    if not isinstance(data, (bytes, bytearray)) or not (8 <= len(data) <= MAX_FONT):
        raise EngineError("font size invalid")
    if bytes(data[:4]) not in (b"wOFF", b"wOF2"):
        raise EngineError("font header invalid")
    minimum = 48 if data[:4] == b'wOF2' else 44
    if len(data) < minimum or int.from_bytes(data[8:12], 'big') != len(data):
        raise EngineError('font header length mismatch')
    return bytes(data)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _lstat(p):
    try:
        return os.lstat(p)
    except FileNotFoundError:
        return None


def _read_regular(path, limit):
    """Read a regular non-symlink file; return (bytes, stat)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        raise EngineError("open %s: %s" % (path, e.strerror))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise EngineError("not a regular/small file: %s" % path)
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(limit + 1), st
    finally:
        os.close(fd)


def _fsync_dir(d):
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _safe_path(base, rel):
    """Reject existing symlink/non-directory parents before any font I/O."""
    current = base
    for part in [''] + rel.split('/')[:-1]:
        if part:
            current = os.path.join(current, part)
        st = _lstat(current)
        if st is not None and not stat.S_ISDIR(st.st_mode):
            raise EngineError('unsafe directory component: ' + current)
    return os.path.join(base, rel)


def _mkdirs(base, rel_dir, mode):
    cur = base
    bst = _lstat(base)
    if bst is None:
        os.mkdir(base, mode)
    elif not stat.S_ISDIR(bst.st_mode):
        raise EngineError('unsafe base directory: ' + base)
    for part in [p for p in rel_dir.split("/") if p]:
        cur = os.path.join(cur, part)
        st = _lstat(cur)
        if st is None:
            os.mkdir(cur, mode)
            os.chmod(cur, mode)
        elif not stat.S_ISDIR(st.st_mode):
            raise EngineError("not a directory (symlink?): %s" % cur)
    return cur


def _atomic_write(path, data, mode):
    d = os.path.dirname(path)
    tmp = os.path.join(d, ".%s.%d.%s.tmp" % (os.path.basename(path), os.getpid(), os.urandom(4).hex()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(d)


class Engine:
    def __init__(self, ui_root, state_root, downloader=None):
        self.ui = os.path.abspath(ui_root)
        self.state = os.path.abspath(state_root)
        self.fonts = os.path.join(self.ui, FONTS_DIRNAME)
        self.cache = os.path.join(self.state, "cache")
        self.mpath = os.path.join(self.state, "manifest.json")
        self.downloader = downloader or _default_download
        self._hook = lambda *a, **k: None  # test seam for crash/race injection
        self._changed = False

    # ---- public API ----
    def status(self):
        self._check_ui()
        m = self._load()
        if os.path.isdir(self.state) and os.path.exists(os.path.join(self.state, "lock")):
            with self._lock(False):
                m = self._load()
                return self._status(m, [])
        return self._status(m, [])

    def reconcile(self):
        return self._op(self._do_reconcile)

    def restore(self):
        return self._op(self._do_restore, True)

    def disable(self):
        def f(m, errs):
            m["disabled"] = True
            self._do_restore(m, errs)
        return self._op(f, True)

    def enable(self):
        def f(m, errs):
            m["disabled"] = False
        return self._op(f)

    # ---- plumbing ----
    def _check_ui(self):
        st = _lstat(self.ui)
        if st is None or not stat.S_ISDIR(st.st_mode):
            raise EngineError("ui_root must be a real directory")

    def _lock(self, exclusive=True):
        class L:
            def __enter__(s):
                s.fd = os.open(os.path.join(self.state, "lock"), os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                fcntl.flock(s.fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)

            def __exit__(s, *a):
                os.close(s.fd)
        return L()

    def _op(self, fn, restoring=False):
        self._check_ui()
        st = _lstat(self.state)
        if st is None:
            os.makedirs(self.state, 0o700)
        elif not stat.S_ISDIR(st.st_mode):
            raise EngineError("state_root must be a real directory")
        self._changed = False
        errs = []
        with self._lock(True):
            m = self._load()
            before = json.dumps(m, sort_keys=True)
            fn(m, errs)
            if json.dumps(m, sort_keys=True) != before or not os.path.exists(self.mpath):
                self._save(m)
            return self._status(m, errs, restoring)

    def _load(self):
        st = _lstat(self.mpath)
        base = {"version": 1, "disabled": False, "fonts": {}, "files": {}}
        if st is None:
            return base
        try:
            data, _ = _read_regular(self.mpath, MAX_TEXT)
            m = json.loads(data)
            checks = [set(m) == set(base), m['version'] == 1, type(m['disabled']) is bool,
                      isinstance(m['fonts'], dict), isinstance(m['files'], dict)]
            for rel, ent in m['fonts'].items():
                checks.extend([_valid_rel(rel), set(ent) == {'sha256', 'size'},
                               bool(re.fullmatch('[a-f0-9]{64}', ent['sha256'])),
                               type(ent['size']) is int and 8 <= ent['size'] <= MAX_FONT])
            for rel, ent in m['files'].items():
                checks.extend([isinstance(rel, str) and not rel.startswith('/') and rel.endswith(('.css','.js')),
                               all(part not in ('', '.', '..') for part in rel.split('/')),
                               set(ent) == {'state','mappings','patched_sha256'},
                               ent['state'] in ('planned','patched'), isinstance(ent['mappings'],list),
                               all(_valid_rel(font) and font in m['fonts'] for font in ent['mappings']),
                               bool(re.fullmatch('[a-f0-9]{64}',ent['patched_sha256']))])
            if not all(checks):
                raise ValueError('invalid ownership journal schema')
        except Exception as e:
            raise EngineError("corrupt manifest: %s" % e)
        base.update(m)
        return base

    def _save(self, m):
        _atomic_write(self.mpath, json.dumps(m, indent=1, sort_keys=True).encode(), 0o600)

    # ---- scanning ----
    def _walk(self):
        skip = {self.fonts, self.state}
        out, symlinks = [], 0
        stack = [self.ui]
        while stack:
            d = stack.pop()
            try:
                it = list(os.scandir(d))
            except OSError as exc:
                raise EngineError("cannot scan UI directory: " + d) from exc
            for e in it:
                if e.is_symlink():
                    symlinks += 1
                elif e.is_dir(follow_symlinks=False):
                    if e.path not in skip:
                        stack.append(e.path)
                elif e.is_file(follow_symlinks=False) and e.name.endswith((".css", ".js")):
                    out.append(e.path)
        return sorted(out), symlinks

    def _analyze(self, text):
        remote = REMOTE_RE.findall(text)
        valid = [t[len(HOST):] for t in remote if _valid_rel(t[len(HOST):])]
        rest = REMOTE_RE.sub(lambda mo: "" if _valid_rel(mo.group(0)[len(HOST):]) else mo.group(0), text)
        unknown = "s81c" in rest.lower()
        local = [t[len(LOCAL_PREFIX):] for t in LOCAL_RE.findall(text)]
        local = [r for r in local if _valid_rel(r)]
        return valid, local, unknown

    def _scan(self, m):
        files = {}
        paths, _ = self._walk()
        for p in paths:
            rel = os.path.relpath(p, self.ui).replace(os.sep, "/")
            try:
                data, st = _read_regular(p, MAX_TEXT)
                text = data.decode("utf-8")
            except (EngineError, UnicodeDecodeError) as e:
                if "s81c" in str(e):
                    pass
                files[rel] = {"state": "error", "detail": "unreadable: %s" % type(e).__name__, "path": p}
                continue
            remote, local, unknown = self._analyze(text)
            if not (remote or local or unknown):
                continue
            info = {"path": p, "remote": sorted(set(remote)), "local": sorted(set(local)), "bytes": data, "st": st}
            owned = rel in m["files"]
            if unknown:
                info["state"] = "unknown_ref"
            elif remote:
                info["state"] = "pending"
            elif owned:
                info["state"] = "patched"
            else:
                info["state"] = "foreign_local"
            files[rel] = info
        return files

    def _clean(self, msg):
        msg = str(msg).replace(self.ui, "<ui>").replace(self.state, "<state>")
        msg = "".join(c if c.isprintable() else "?" for c in msg)
        return msg[:200]

    def _font_matches(self, m, rel):
        ent = m['fonts'].get(rel)
        if not ent or not self._marker_mine():
            return False
        try:
            data, _ = _read_regular(_safe_path(self.fonts, rel), MAX_FONT)
            return len(data) == ent['size'] and _sha(data) == ent['sha256']
        except (EngineError, OSError):
            return False

    def _status(self, m, errs, restoring=False):
        files = self._scan(m)
        errs = list(errs)
        for rel, info in files.items():
            if rel in m['files']:
                for font in info.get('local', []):
                    if font in m['files'][rel]['mappings'] and not self._font_matches(m, font):
                        info['state'] = 'error'
                        errs.append('missing or corrupt published font: ' + font)
        errs = [self._clean(e) for e in errs[:20]]
        fe = getattr(self, "_file_errs", {})
        for rel, msg in fe.items():
            if rel in files and files[rel]["state"] == "pending":
                files[rel]["state"] = "missing_fonts"
            files.get(rel, {}).setdefault("detail", self._clean(msg))
        leftover = sorted(r for r, i in files.items() if i.get("local") and r not in m["files"] or
                          (i.get("local") and r in m["files"]))
        out = {}
        for rel, i in files.items():
            d = {"state": i["state"]}
            for k in ("detail",):
                if k in i:
                    d[k] = i[k]
            if "remote" in i:
                d["remote"] = len(i["remote"])
                d["local"] = len(i["local"])
            out[rel] = d
        bad = {"pending", "unknown_ref", "missing_fonts", "error"}
        if m["disabled"] or restoring:
            bad = {"error"}
        if not restoring and not m['disabled'] and not any(i.get('remote') or i.get('local') for i in files.values()):
            errs.append('no supported font references found; check UI layout')
        ok = not errs and not any(d["state"] in bad for d in out.values())
        if restoring and leftover:
            ok = False
            errs.append("local font references remain in: " + ", ".join(leftover[:5])[:150])
        return {"ok": ok, "changed": self._changed, "disabled": m["disabled"], "files": out,
                "fonts": {"owned": len(m["fonts"])}, "errors": errs}

    # ---- fonts ----
    def _prepare_fonts_dir(self):
        st = _lstat(self.fonts)
        if st is None:
            os.mkdir(self.fonts, 0o755)
            os.chmod(self.fonts, 0o755)
            _atomic_write(os.path.join(self.fonts, MARKER), self._marker_bytes(), 0o644)
            return
        if not stat.S_ISDIR(st.st_mode):
            raise EngineError("local-fonts is not a real directory")
        mk = _lstat(os.path.join(self.fonts, MARKER))
        if mk is not None and stat.S_ISREG(mk.st_mode):
            if not self._marker_mine():
                raise EngineError("local-fonts owned by another instance")
            return
        if os.listdir(self.fonts):
            raise EngineError("foreign local-fonts directory (no ownership marker)")
        _atomic_write(os.path.join(self.fonts, MARKER), self._marker_bytes(), 0o644)

    def _marker_bytes(self):
        return ("owner=%s\n" % self.state).encode()

    def _marker_mine(self):
        try:
            data, _ = _read_regular(os.path.join(self.fonts, MARKER), 4096)
        except EngineError:
            return False
        return data == self._marker_bytes()

    def _ensure_font(self, m, rel):
        if not _valid_rel(rel):
            raise EngineError("invalid font path")
        ent = m["fonts"].get(rel)
        cache = _safe_path(self.cache, rel)
        data = None
        if _lstat(cache) is not None:
            try:
                d, _ = _read_regular(cache, MAX_FONT)
                d = _check_font(d)
                if not ent or ent["sha256"] == _sha(d):
                    data = d
            except EngineError:
                data = None
        if data is None:
            try:
                data = _check_font(self.downloader(HOST + rel))
            except EngineError:
                raise
            except Exception as e:
                raise EngineError("download %s failed: %s" % (rel, type(e).__name__))
            if ent and _sha(data) != ent['sha256']:
                raise EngineError('download differs from pinned font hash: ' + rel)
            _mkdirs(self.cache, os.path.dirname(rel), 0o700)
            _atomic_write(cache, data, 0o644)
        sha = _sha(data)
        pub = _safe_path(self.fonts, rel)
        st = _lstat(pub)
        if st is not None:
            if not stat.S_ISREG(st.st_mode):
                raise EngineError("published font path is not a regular file: %s" % rel)
            cur, _ = _read_regular(pub, MAX_FONT)
            if cur == data:
                m["fonts"][rel] = {"sha256": sha, "size": len(data)}
                return
            if not ent:
                raise EngineError("foreign font file conflict: %s" % rel)
        _mkdirs(self.fonts, os.path.dirname(rel), 0o755)
        _atomic_write(pub, data, 0o644)
        m["fonts"][rel] = {"sha256": sha, "size": len(data)}

    # ---- file replacement ----
    def _replace(self, path, st, old, new):
        d = os.path.dirname(path)
        tmp = os.path.join(d, ".%s.lf%s.tmp" % (os.path.basename(path), os.urandom(4).hex()))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            try:
                with os.fdopen(fd, "wb", closefd=False) as f:
                    f.write(new)
                    f.flush()
                os.fchmod(fd, stat.S_IMODE(st.st_mode))
                if (st.st_uid, st.st_gid) != (os.geteuid(), os.getegid()):
                    os.fchown(fd, st.st_uid, st.st_gid)
                try:
                    names = os.listxattr(path, follow_symlinks=False)
                except OSError:
                    names = []
                for n in names:
                    os.setxattr(tmp, n, os.getxattr(path, n, follow_symlinks=False), follow_symlinks=False)
                os.fsync(fd)
            finally:
                os.close(fd)
            self._hook("before_replace", path)
            cur, cst = _read_regular(path, MAX_TEXT)
            if cur != old or (cst.st_dev, cst.st_ino) != (st.st_dev, st.st_ino):
                raise EngineError("source changed during patch: %s" % path)
            for ext in (".gz", ".br"):
                sp = path + ext
                sst = _lstat(sp)
                if sst is not None and stat.S_ISREG(sst.st_mode):
                    os.unlink(sp)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        _fsync_dir(d)
        self._changed = True
        self._hook("after_replace", path)

    # ---- operations ----
    def _recover(self, m, files):
        for rel in list(m["files"]):
            ent = m["files"][rel]
            i = files.get(rel)
            if i is not None and i.get("state") == "error":
                continue  # retain ownership until the file can be read safely
            if i is None or not (set(ent["mappings"]) & set(i.get("local", []))):
                del m["files"][rel]  # file gone/rewritten by UI update: ownership lapsed
            elif ent["state"] == "planned" and _sha(i["bytes"]) == ent["patched_sha256"]:
                ent["state"] = "patched"

    def _do_reconcile(self, m, errs):
        if m["disabled"]:
            return
        self._file_errs = {}
        files = self._scan(m)
        self._recover(m, files)
        # self-heal published fonts of owned files
        for rel, ent in m["files"].items():
            for fr in ent["mappings"]:
                if fr in files[rel].get("local", []):
                    if not self._font_matches(m, fr):
                        try:
                            self._prepare_fonts_dir()
                            self._ensure_font(m, fr)
                        except (EngineError, OSError) as e:
                            errs.append("heal %s: %s" % (fr, e))
        for rel, i in files.items():
            if i["state"] != "pending":
                continue
            try:
                self._patch_one(m, rel, i)
            except (EngineError, OSError) as e:
                self._file_errs[rel] = str(e)
                errs.append("%s: %s" % (rel, e))
                self._save(m)

    def _patch_one(self, m, rel, i):
        self._prepare_fonts_dir()
        for fr in i["remote"]:
            self._ensure_font(m, fr)
        text = i["bytes"].decode("utf-8")
        new = REMOTE_RE.sub(lambda mo: LOCAL_PREFIX + mo.group(0)[len(HOST):], text).encode("utf-8")
        old = m["files"].get(rel, {"mappings": []})["mappings"]
        m["files"][rel] = {"state": "planned", "mappings": sorted(set(old) | set(i["remote"])),
                           "patched_sha256": _sha(new)}
        self._save(m)  # journal: planned reversible mappings before touching the file
        self._replace(i["path"], i["st"], i["bytes"], new)
        m["files"][rel]["state"] = "patched"
        self._save(m)

    def _do_restore(self, m, errs):
        self._file_errs = {}
        files = self._scan(m)
        for rel in list(m["files"]):
            ent, i = m["files"][rel], files.get(rel)
            if i is None:
                del m["files"][rel]
                continue
            maps = set(ent["mappings"])
            text = i["bytes"].decode("utf-8") if "bytes" in i else None
            if text is None:
                errs.append("%s: unreadable" % rel)
                continue

            def back(mo):
                r = mo.group(0)[len(LOCAL_PREFIX):]
                return HOST + r if r in maps else mo.group(0)
            new = LOCAL_RE.sub(back, text).encode("utf-8")
            try:
                if new != i["bytes"]:
                    self._replace(i["path"], i["st"], i["bytes"], new)
                del m["files"][rel]
            except (EngineError, OSError) as e:
                errs.append("%s: %s" % (rel, e))
        # A partial scan cannot prove that a font is unreferenced.
        if any(info['state'] == 'error' for info in files.values()):
            errs.append('font cleanup refused: unreadable UI assets')
            return
        # remove owned fonts that nothing references any more
        referenced = set()
        for i in self._scan(m).values():
            referenced.update(i.get("local", []))
        for fr in list(m["fonts"]):
            if fr in referenced:
                continue
            try:
                p = _safe_path(self.fonts, fr)
                st = _lstat(p)
                if st is not None:
                    if not stat.S_ISREG(st.st_mode) or not self._font_matches(m, fr):
                        errs.append('refusing to delete modified or foreign font: ' + fr)
                        continue
                    os.unlink(p)
                    self._changed = True
                del m["fonts"][fr]
            except (EngineError, OSError) as e:
                errs.append("font %s: %s" % (fr, e))
        if not m["fonts"] and not m["files"]:
            self._cleanup_fonts_dir()

    def _cleanup_fonts_dir(self):
        st = _lstat(self.fonts)
        if st is None or not stat.S_ISDIR(st.st_mode) or not self._marker_mine():
            return
        def prune(d):
            for n in os.listdir(d):
                c = os.path.join(d, n)
                cs = _lstat(c)
                if cs is not None and stat.S_ISDIR(cs.st_mode):
                    prune(c)
                    if not os.listdir(c):
                        os.rmdir(c)
        prune(self.fonts)
        if os.listdir(self.fonts) == [MARKER]:
            os.unlink(os.path.join(self.fonts, MARKER))
            os.rmdir(self.fonts)
            self._changed = True
