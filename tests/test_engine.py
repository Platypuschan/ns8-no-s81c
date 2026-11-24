"""Tests for localfonts.engine. Font bytes are SYNTHETIC fixtures, not real fonts."""
import hashlib, json, os, stat, sys, tempfile, unittest, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "imageroot/pypkg"))
from localfonts.engine import Engine, EngineError, _NoRedirect

H = "https://1.www.s81c.com/"
P = "common/carbon/plex/fonts/"
F1, F2 = P + "IBM-Plex-Sans/a.woff2", P + "IBM-Plex-Mono/b.woff"
LOC = "/cluster-admin/local-fonts/"


def synth(rel, magic=b"wOF2"):
    # Header-shaped synthetic bytes, deliberately not a renderable font.
    payload = b'SYNTHETIC-TEST-FIXTURE:' + rel.encode()
    header_size = 48 if magic == b'wOF2' else 44
    return magic + b'\x00\x01\x00\x00' + (header_size + len(payload)).to_bytes(4, 'big') + b'\x00' * (header_size - 12) + payload


class FakeDL:
    def __init__(self, overrides=None):
        self.calls, self.overrides = [], overrides or {}

    def __call__(self, url):
        self.calls.append(url)
        rel = url[len(H):]
        if rel in self.overrides:
            return self.overrides[rel]
        return synth(rel, b"wOFF" if rel.endswith(".woff") else b"wOF2")


def css(*rels):
    return "".join("@font-face{src:url(%s%s) format('x')}\n" % (H, r) for r in rels)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        r = os.path.realpath(self.tmp.name)
        self.ui, self.st, self.out = [os.path.join(r, n) for n in ("ui", "state", "outside")]
        for d in (self.ui, self.out):
            os.makedirs(d)
        self.dl = FakeDL()
        self.e = Engine(self.ui, self.st, downloader=self.dl)

    def w(self, rel, text, mode=0o644):
        p = os.path.join(self.ui, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, mode)
        return p

    def r(self, rel):
        with open(os.path.join(self.ui, rel)) as f:
            return f.read()


class TestPatch(Base):
    def test_patches_and_publishes(self):
        self.w("a.css", css(F1, F2))
        s = self.e.reconcile()
        self.assertTrue(s["ok"]); self.assertTrue(s["changed"])
        self.assertNotIn("s81c", self.r("a.css"))
        self.assertIn(LOC + F1, self.r("a.css"))
        pub = os.path.join(self.ui, "local-fonts", F1)
        self.assertEqual(Path(pub).read_bytes(), synth(F1))
        self.assertEqual(stat.S_IMODE(os.stat(pub).st_mode), 0o644)
        self.assertEqual(sorted(self.dl.calls), sorted([H + F1, H + F2]))
        self.assertTrue(os.path.exists(os.path.join(self.st, "cache", F1)))

    def test_repeat_is_noop(self):
        p = self.w("a.css", css(F1))
        self.e.reconcile()
        ino, mt = os.stat(p).st_ino, os.stat(p).st_mtime_ns
        n = len(self.dl.calls)
        s = self.e.reconcile()
        self.assertFalse(s["changed"]); self.assertEqual(len(self.dl.calls), n)
        self.assertEqual((os.stat(p).st_ino, os.stat(p).st_mtime_ns), (ino, mt))

    def test_domain_prose_is_not_an_external_request(self):
        self.w('a.css', css(F1))
        prose = "const help = 'No request to s81c.com is needed in the browser';"
        self.w('apps/no-s81c1/module.js', prose)
        self.assertTrue(self.e.reconcile()['ok'])
        self.assertEqual(self.r('apps/no-s81c1/module.js'), prose)

    def test_module_identity_is_not_an_external_domain_reference(self):
        self.w('a.css', css(F1))
        original = "const instance = 'no-s81c1';"
        self.w('apps/no-s81c1/module.js', original)
        result = self.e.reconcile()
        self.assertTrue(result['ok'])
        self.assertEqual(self.r('apps/no-s81c1/module.js'), original)

    def test_js_patched_other_ext_ignored(self):
        self.w("a.js", 'x="%s%s"' % (H, F1))
        self.w("a.txt", css(F1))
        self.e.reconcile()
        self.assertIn(LOC + F1, self.r("a.js"))
        self.assertIn("s81c", self.r("a.txt"))

    def test_preserves_mode(self):
        p = self.w("a.css", css(F1), 0o640)
        self.e.reconcile()
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o640)

    def test_preserves_xattr(self):
        p = self.w("a.css", css(F1))
        try:
            os.setxattr(p, "user.t", b"v")
        except OSError:
            self.skipTest("no user xattr support")
        self.e.reconcile()
        self.assertEqual(os.getxattr(p, "user.t"), b"v")

    def test_ui_update_same_path_repatched(self):
        self.w("a.css", css(F1))
        self.e.reconcile()
        self.w("a.css", css(F1, F2))  # fresh upstream content
        s = self.e.reconcile()
        self.assertTrue(s["changed"])
        self.assertNotIn("s81c", self.r("a.css"))
        self.assertIn(LOC + F2, self.r("a.css"))

    def test_precompressed_siblings_invalidated(self):
        self.w("a.css", css(F1)); self.w("a.css.gz", "x"); self.w("a.css.br", "x"); self.w("b.css.gz", "x")
        self.e.reconcile()
        self.assertFalse(os.path.exists(os.path.join(self.ui, "a.css.gz")))
        self.assertFalse(os.path.exists(os.path.join(self.ui, "a.css.br")))
        self.assertTrue(os.path.exists(os.path.join(self.ui, "b.css.gz")))

    def test_status_detects_missing_publication_and_reconcile_repairs(self):
        self.w('a.css', css(F1))
        self.e.reconcile()
        pub = Path(self.ui, 'local-fonts', F1)
        pub.unlink()
        state = Engine(self.ui, self.st, downloader=self.dl).status()
        self.assertFalse(state['ok'])
        self.assertTrue(self.e.reconcile()['ok'])
        self.assertEqual(pub.read_bytes(), synth(F1))

    def test_status_detects_same_size_corruption_and_reconcile_repairs(self):
        self.w('a.css', css(F1))
        self.e.reconcile()
        pub = Path(self.ui, 'local-fonts', F1)
        pub.write_bytes(synth(F1)[:-1] + b'!')
        self.assertFalse(Engine(self.ui, self.st, downloader=self.dl).status()['ok'])
        self.assertTrue(self.e.reconcile()['ok'])
        self.assertEqual(pub.read_bytes(), synth(F1))

    def test_status_readonly(self):
        self.w("a.css", css(F1))
        s = self.e.status()
        self.assertEqual(self.dl.calls, [])
        self.assertFalse(os.path.exists(self.st))
        self.assertEqual(self.r("a.css"), css(F1))
        self.assertEqual(s["files"]["a.css"]["state"], "pending")
        self.assertFalse(s["ok"])


class TestFailClosed(Base):
    def test_symlinked_cache_root_is_rejected(self):
        Path(self.st).mkdir()
        os.symlink(self.out, Path(self.st, 'cache'))
        self.w('a.css', css(F1))
        result = self.e.reconcile()
        self.assertFalse(result['ok'])
        self.assertEqual(list(Path(self.out).iterdir()), [])

    def test_restore_does_not_follow_replaced_publication_parent(self):
        self.w('a.css', css(F1))
        self.e.reconcile()
        fontdir = Path(self.ui, 'local-fonts', 'common')
        import shutil
        shutil.copytree(fontdir, Path(self.out, 'common'))
        shutil.rmtree(fontdir)
        os.symlink(Path(self.out, 'common'), fontdir)
        victim = Path(self.out, 'common', F1.removeprefix('common/'))
        result = self.e.restore()
        self.assertFalse(result['ok'])
        self.assertTrue(victim.exists(), 'restore must not unlink through symlink directory')

    def test_corrupt_manifest_paths_fail_before_restore(self):
        self.w('a.css', css(F1))
        self.e.reconcile()
        manifest = Path(self.st, 'manifest.json')
        data = json.loads(manifest.read_text())
        data['fonts']['../../victim.woff2'] = data['fonts'].pop(F1)
        manifest.write_text(json.dumps(data))
        with self.assertRaises(EngineError):
            self.e.restore()

    def test_rejected_refs(self):
        bad = [H + F1 + "?v=1", H + F1 + "#x", H + P + "../x.woff2", H + P + "%2e%2e/x.woff2",
               H + "other/x.woff2", H + P + "a.WOFF2", H + P + "a.ttf", H + P + "a//b.woff2",
               "http://1.www.s81c.com/" + F1, "//1.www.s81c.com/" + F1, "https://2.www.s81c.com/" + F1,
               "https:\\/\\/1.www.s81c.com\\/" + F1]
        for i, b in enumerate(bad):
            with self.subTest(b):
                orig = "a{src:url(%s) url(%s%s)}" % (b, H, F1)
                self.w("a%d.css" % i, orig)
                s = self.e.reconcile()
                self.assertEqual(self.r("a%d.css" % i), orig)
                self.assertFalse(s["ok"])
                self.assertEqual(s["files"]["a%d.css" % i]["state"], "unknown_ref")

    def test_unknown_in_one_file_doesnt_block_other(self):
        self.w("bad.css", "url(https://1.www.s81c.com/evil/x.woff2)")
        self.w("good.css", css(F1))
        s = self.e.reconcile()
        self.assertIn(LOC, self.r("good.css")); self.assertFalse(s["ok"])

    def test_upstream_drift_does_not_replace_pinned_font(self):
        self.w('a.css', css(F1))
        self.e.reconcile()
        Path(self.st, 'cache', F1).unlink()
        Path(self.ui, 'local-fonts', F1).unlink()
        self.dl.overrides[F1] = synth(F1)[:-1] + b'!'
        self.assertFalse(self.e.reconcile()['ok'])
        self.assertFalse(Path(self.ui, 'local-fonts', F1).exists())

    def test_truncated_font_header_length_rejected(self):
        self.dl.overrides[F1] = synth(F1)[:-10]
        self.w('a.css', css(F1))
        self.assertFalse(self.e.reconcile()['ok'])
        self.assertEqual(self.r('a.css'), css(F1))

    def test_html_rejected_file_unpatched(self):
        self.dl.overrides[F2] = b"<html>not a font</html>"
        self.w("a.css", css(F1, F2))
        s = self.e.reconcile()
        self.assertEqual(self.r("a.css"), css(F1, F2))
        self.assertEqual(s["files"]["a.css"]["state"], "missing_fonts")
        self.assertFalse(os.path.exists(os.path.join(self.st, "cache", F2)))

    def test_oversize_and_tiny_rejected(self):
        self.dl.overrides[F1] = b"wOF2" + b"\0" * (5 * 1024 * 1024)
        self.dl.overrides[F2] = b"wOFF"
        self.w("a.css", css(F1)); self.w("b.css", css(F2))
        self.e.reconcile()
        self.assertEqual(self.r("a.css"), css(F1)); self.assertEqual(self.r("b.css"), css(F2))

    def test_downloader_exception(self):
        def boom(u): raise OSError("net down")
        e = Engine(self.ui, self.st, downloader=boom)
        self.w("a.css", css(F1))
        s = e.reconcile()
        self.assertEqual(self.r("a.css"), css(F1)); self.assertFalse(s["ok"])

    def test_symlinks_skipped(self):
        victim = os.path.join(self.out, "v.css"); Path(victim).write_text(css(F1))
        os.symlink(victim, os.path.join(self.ui, "l.css"))
        os.symlink(self.out, os.path.join(self.ui, "ld"))
        self.e.reconcile()
        self.assertEqual(Path(victim).read_text(), css(F1))

    def test_symlink_ui_root_rejected(self):
        os.symlink(self.ui, os.path.join(self.out, "uil"))
        e = Engine(os.path.join(self.out, "uil"), self.st, downloader=self.dl)
        with self.assertRaises(EngineError):
            e.reconcile()

    def test_symlinked_fonts_dir_or_font_rejected(self):
        os.symlink(self.out, os.path.join(self.ui, "local-fonts"))
        self.w("a.css", css(F1))
        s = self.e.reconcile()
        self.assertEqual(self.r("a.css"), css(F1)); self.assertFalse(s["ok"])
        self.assertEqual(os.listdir(self.out), [])

    def test_foreign_fonts_dir_conflict(self):
        os.makedirs(os.path.join(self.ui, "local-fonts")); Path(self.ui, "local-fonts", "x").write_text("1")
        self.w("a.css", css(F1))
        s = self.e.reconcile()
        self.assertEqual(self.r("a.css"), css(F1)); self.assertFalse(s["ok"])

    def test_second_instance_refused(self):
        self.w("a.css", css(F1)); self.e.reconcile()
        e2 = Engine(self.ui, self.st + "2", downloader=self.dl)
        self.w("b.css", css(F2))
        s = e2.reconcile()
        self.assertFalse(s["ok"]); self.assertEqual(self.r("b.css"), css(F2))
        self.assertTrue(os.path.exists(os.path.join(self.ui, "local-fonts", F1)))
        e2.restore()
        self.assertTrue(os.path.exists(os.path.join(self.ui, "local-fonts", F1)))

    def test_errors_bounded_no_paths(self):
        def boom(u): raise OSError(self.st + "/secret " + "x" * 500)
        s = Engine(self.ui, self.st, downloader=boom)
        self.w("a.css", css(F1))
        r = s.reconcile()
        for e in r["errors"]:
            self.assertLessEqual(len(e), 200); self.assertNotIn(self.ui, e); self.assertNotIn(self.st, e)

    def test_restore_not_ok_while_local_refs_remain(self):
        self.w("a.css", css(F1)); self.e.reconcile()
        self.w("unowned.css", "y{src:url(%s%s)}" % (LOC, F1))
        self.assertFalse(self.e.restore()["ok"])

    def test_foreign_font_conflict(self):
        self.w("pre.css", css(F2)); self.e.reconcile()  # creates dir+marker
        d = os.path.join(self.ui, "local-fonts", os.path.dirname(F1)); os.makedirs(d)
        Path(self.ui, "local-fonts", F1).write_bytes(b"wOF2other")
        self.w("a.css", css(F1))
        s = self.e.reconcile()
        self.assertEqual(self.r("a.css"), css(F1)); self.assertFalse(s["ok"])
        self.assertEqual(Path(self.ui, "local-fonts", F1).read_bytes(), b"wOF2other")

    def test_source_changed_before_replace(self):
        p = self.w("a.css", css(F1))
        def hook(name, path=None):
            if name == "before_replace":
                Path(p).write_text(css(F1) + "/*new*/")
        self.e._hook = hook
        s = self.e.reconcile()
        self.assertFalse(s["ok"])
        self.assertEqual(self.r("a.css"), css(F1) + "/*new*/")
        self.assertEqual([n for n in os.listdir(self.ui) if n.endswith(".tmp")], [])

    def test_default_downloader_no_redirect(self):
        h = _NoRedirect()
        self.assertIsNone(h.redirect_request(None, None, 302, "x", {}, "https://evil/"))


class TestRestore(Base):
    def test_unreadable_owned_file_preserves_fonts_and_journal(self):
        self.w('a.css', css(F1))
        self.e.reconcile()
        Path(self.ui, 'a.css').write_bytes(b'\xff' + (LOC + F1).encode())
        result = self.e.restore()
        self.assertFalse(result['ok'])
        self.assertTrue(Path(self.ui, 'local-fonts', F1).exists())
        self.assertIn('a.css', json.loads(Path(self.st,'manifest.json').read_text())['files'])

    def test_directory_scan_failure_is_not_silently_healthy(self):
        from unittest.mock import patch
        self.w('sub/a.css', css(F1))
        self.e.reconcile()
        original_scandir = os.scandir
        def broken(path):
            if str(path) == str(Path(self.ui,'sub')):
                raise PermissionError('injected scan failure')
            return original_scandir(path)
        with patch('localfonts.engine.os.scandir', side_effect=broken):
            with self.assertRaises(EngineError):
                self.e.restore()
        self.assertTrue(Path(self.ui,'local-fonts',F1).exists())

    def test_empty_enabled_ui_is_not_healthy(self):
        self.assertFalse(self.e.status()['ok'])

    def test_restore_preserves_foreign_modified_font(self):
        self.w('a.css', css(F1))
        self.e.reconcile()
        font = Path(self.ui, 'local-fonts', F1)
        font.write_bytes(b'FOREIGN-CONTENT')
        result = self.e.restore()
        self.assertFalse(result['ok'])
        self.assertEqual(font.read_bytes(), b'FOREIGN-CONTENT')
        self.assertEqual(self.r('a.css'), css(F1))

    def test_restore_roundtrip(self):
        orig = css(F1, F2)
        self.w("a.css", orig); self.e.reconcile()
        s = self.e.restore()
        self.assertTrue(s["ok"]); self.assertEqual(self.r("a.css"), orig)
        self.assertFalse(os.path.exists(os.path.join(self.ui, "local-fonts", F1)))
        self.assertFalse(os.path.exists(os.path.join(self.ui, "local-fonts")))
        self.assertEqual(self.e.restore()["changed"], False)

    def test_restore_does_not_clobber_fresh_file(self):
        self.w("a.css", css(F1)); self.e.reconcile()
        fresh = "/* new release */" + css(F2)
        self.w("a.css", fresh)
        self.e.restore()
        self.assertEqual(self.r("a.css"), fresh)

    def test_restore_only_owned_occurrences(self):
        self.w("a.css", css(F1)); self.e.reconcile()
        self.w("a.css", self.r("a.css") + "x{src:url(%sother.woff2)}" % LOC)
        self.w("unowned.css", "y{src:url(%s%s)}" % (LOC, F1))
        self.e.restore()
        self.assertIn(LOC + "other.woff2", self.r("a.css"))
        self.assertIn(H + F1, self.r("a.css"))
        self.assertEqual(self.r("unowned.css"), "y{src:url(%s%s)}" % (LOC, F1))

    def test_shared_font_kept_while_referenced(self):
        self.w("a.css", css(F1, F2)); self.e.reconcile()
        self.w("unowned.css", "y{src:url(%s%s)}" % (LOC, F1))
        s = self.e.restore()
        pub = os.path.join(self.ui, "local-fonts")
        self.assertTrue(os.path.exists(os.path.join(pub, F1)))
        self.assertFalse(os.path.exists(os.path.join(pub, F2)))

    def test_disable_blocks_reconcile_until_enable(self):
        self.w("a.css", css(F1)); self.e.reconcile()
        s = self.e.disable()
        self.assertTrue(s["disabled"]); self.assertEqual(self.r("a.css"), css(F1))
        self.assertFalse(self.e.reconcile()["changed"]); self.assertEqual(self.r("a.css"), css(F1))
        self.e.enable(); self.e.reconcile()
        self.assertIn(LOC, self.r("a.css"))

    def test_crash_before_replace_recoverable(self):
        self.w("a.css", css(F1))
        def hook(name, path=None):
            if name == "before_replace": raise KeyboardInterrupt
        self.e._hook = hook
        with self.assertRaises(KeyboardInterrupt):
            self.e.reconcile()
        self.assertEqual(self.r("a.css"), css(F1))
        self.e._hook = lambda *a, **k: None
        self.assertTrue(self.e.reconcile()["ok"]); self.assertIn(LOC, self.r("a.css"))

    def test_crash_after_replace_restorable(self):
        self.w("a.css", css(F1))
        def hook(name, path=None):
            if name == "after_replace": raise KeyboardInterrupt
        self.e._hook = hook
        with self.assertRaises(KeyboardInterrupt):
            self.e.reconcile()
        self.e._hook = lambda *a, **k: None
        self.e.restore()
        self.assertEqual(self.r("a.css"), css(F1))

    def test_manifest_private_atomic(self):
        self.w("a.css", css(F1)); self.e.reconcile()
        m = os.path.join(self.st, "manifest.json")
        self.assertEqual(stat.S_IMODE(os.stat(m).st_mode), 0o600)
        self.assertIn("a.css", json.loads(Path(m).read_text())["files"])


if __name__ == "__main__":
    unittest.main()
