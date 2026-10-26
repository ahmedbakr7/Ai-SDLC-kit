"""ADR-0009: binary files come from a declared generator or a pinned source. Each rule has a
test that catches the defect it exists for and one that shows the reference passes."""
import hashlib
import io
import json
import sys
import unittest
from unittest import mock

from helpers import ProductRepo, git
from sdlc import assets, config
from sdlc.gate import hard_reason

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256))
SHA = hashlib.sha256(PNG).hexdigest()


def decl(path: str = "app/static/logo.png", sha: str = SHA, extra: str = 'generate = "true"') -> str:
    return f'[[asset]]\npath = "{path}"\nsha256 = "{sha}"\n{extra}\n'


class Check(unittest.TestCase):
    def setUp(self) -> None:
        self.p = ProductRepo()

    def tearDown(self) -> None:
        self.p.close()

    def set_mode(self, mode: str) -> None:
        self.p.write("sdlc.toml", self.p.read("sdlc.toml") + f'\n[assets]\nmode = "{mode}"\n')

    def branch(self) -> None:
        git(self.p.root, "checkout", "-q", "-b", "work")

    def add_binary(self, rel: str = "app/static/logo.png", data: bytes = PNG, commit: bool = True) -> None:
        f = self.p.root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        if commit:
            self.p.commit("binary")

    def ci(self) -> dict:
        self.p.sdlc("gate", "ci", "--base", "main", "--only", "assets")
        return json.loads(self.p.read(".sdlc-run/ci.json"))["checks"][0]

    def test_no_binary_passes(self) -> None:
        self.branch()
        self.p.write("README.md", "# text only\n")
        self.p.commit("text")
        c = self.ci()
        self.assertEqual((c["status"], c["summary"]), ("pass", "no binary files changed"))

    def test_an_undeclared_binary_warns_by_default(self) -> None:
        self.branch()
        self.add_binary()
        c = self.ci()
        self.assertEqual(c["status"], "pass")
        self.assertTrue(c["summary"].startswith("WARNING 1 binary file problem(s)"), c)
        self.assertIn("app/static/logo.png: binary, not declared in assets.toml", c["details"][0])

    def test_fail_mode_fails_an_undeclared_binary(self) -> None:
        self.set_mode("fail")
        self.p.commit("lead: assets fail")
        self.branch()
        self.add_binary()
        c = self.ci()
        self.assertEqual(c["status"], "fail")

    def test_a_declared_matching_binary_passes(self) -> None:
        self.set_mode("fail")
        self.p.write("assets.toml", decl())
        self.p.commit("lead: declare the logo")
        self.branch()
        self.add_binary()
        c = self.ci()
        self.assertEqual(c["status"], "pass", c)
        self.assertEqual(c["summary"], "1 binary file(s), each declared with a matching sha256")

    def test_a_binary_that_differs_from_its_hash_fails(self) -> None:
        self.set_mode("fail")
        self.p.write("assets.toml", decl())
        self.p.commit("lead: declare the logo")
        self.branch()
        self.add_binary(data=PNG + b"\x00tampered")
        c = self.ci()
        self.assertEqual(c["status"], "fail")
        self.assertIn("app/static/logo.png: sha256 differs from assets.toml", c["details"][0])

    def test_a_ticket_play_reads_the_declarations_from_the_base(self) -> None:
        self.set_mode("fail")
        self.p.commit("lead: assets fail")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.p.write("assets.toml", decl())  # declared on the branch only
        self.add_binary()
        self.p.sdlc("gate", "build", "T-042-02", "--only", "assets")
        c = json.loads(self.p.read(".sdlc-run/T-042-02.build.json"))["checks"][0]
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("not declared in assets.toml", c["details"][0])

    def test_a_ticket_play_passes_with_a_base_declaration(self) -> None:
        self.set_mode("fail")
        self.p.write("assets.toml", decl())
        self.p.commit("lead: declare the logo")
        git(self.p.root, "checkout", "-q", "-b", "build/T-042-02")
        self.add_binary()
        self.p.sdlc("gate", "build", "T-042-02", "--only", "assets")
        c = json.loads(self.p.read(".sdlc-run/T-042-02.build.json"))["checks"][0]
        self.assertEqual(c["status"], "pass", c)

    def test_the_branchs_gitattributes_cannot_hide_a_binary(self) -> None:
        # PR #60 review: `*.png diff` makes numstat count a PNG's lines; its bytes still say binary.
        self.set_mode("fail")
        self.p.commit("lead: assets fail")
        self.branch()
        self.p.write("app/.gitattributes", "*.png diff\n")
        self.add_binary()
        c = self.ci()
        self.assertEqual(c["status"], "fail", c)
        self.assertIn("app/static/logo.png: binary, not declared", c["details"][0])

    def test_a_git_error_fails_the_check(self) -> None:
        from sdlc import gitutil
        self.branch()
        self.add_binary()
        with mock.patch("sdlc.assets.binaries", side_effect=gitutil.GitError("no merge base")):
            c = self.ci()
        self.assertEqual((c["status"], c["summary"]), ("fail", "cannot list binary files: no merge base"))

    def test_gitattributes_decides_what_is_binary(self) -> None:
        self.p.write(".gitattributes", "*.dat binary\n")
        self.p.commit("lead: attributes")
        self.branch()
        self.p.write("app/data.dat", "plain text, marked binary\n")
        self.p.write("app/icon.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>\n")
        self.p.commit("files")
        c = self.ci()
        self.assertEqual(len(c["details"]), 1, c)
        self.assertIn("app/data.dat: binary", c["details"][0])

    def test_untracked_binaries_count_and_deleted_ones_do_not(self) -> None:
        self.add_binary("app/static/old.png")
        self.branch()
        (self.p.root / "app/static/old.png").unlink()
        self.p.commit("delete a binary")
        self.add_binary("app/static/new.png", commit=False)
        self.assertEqual(assets.binaries(self.p.root, "main"), ["app/static/new.png"])

    def test_a_bad_mode_fails(self) -> None:
        self.set_mode("loud")
        self.p.commit("lead: typo")
        self.branch()
        self.add_binary()
        c = self.ci()
        self.assertEqual((c["status"], c["summary"]), ("fail", "assets.mode must be warn or fail, got 'loud'"))

    def test_the_declarations_are_a_lead_artifact(self) -> None:
        cfg = config.load(self.p.root)
        self.assertIn("a lead artifact", hard_reason(cfg, "assets.toml", "build", None))


class Declarations(unittest.TestCase):
    def test_valid_declarations(self) -> None:
        got, probs = assets.parse(decl() + decl("b.bin", extra='source = "https://example.org/b.bin"'))
        self.assertEqual(probs, [])
        self.assertEqual([(a.path, a.generate, a.source) for a in got],
                         [("app/static/logo.png", "true", ""), ("b.bin", "", "https://example.org/b.bin")])

    def test_each_mistake_is_named(self) -> None:
        cases = {
            decl(sha="abc"): "sha256 must be 64 hex characters",
            decl(extra='generate = "x"\nsource = "https://e.org/a"'): "set exactly one of generate",
            decl(extra=""): "set exactly one of generate",
            decl(extra='source = "http://e.org/a"'): "source must be an https:// URL",
            decl("../etc/x"): "path must be a plain relative path inside the repository",
            decl("/abs"): "path must be a plain relative path inside the repository",
            decl("./a.png"): "path must be a plain relative path",
            decl("a//b.png"): "path must be a plain relative path",
            decl("a\\\\b.png"): "path must be a plain relative path",
            decl() + decl(): "declared twice",
            "[[asset]\n": "not valid TOML",
            "asset = 1\n": "want [[asset]] tables",
        }
        for text, want in cases.items():
            with self.subTest(want=want):
                _, probs = assets.parse(text)
                self.assertTrue(any(want in p for p in probs), probs)
        self.assertEqual(assets.parse(None), ([], []))


class Command(unittest.TestCase):
    def setUp(self) -> None:
        self.p = ProductRepo()
        gen = f'"{sys.executable}" -c "import pathlib; pathlib.Path(\'app/static\').mkdir(parents=True, exist_ok=True); pathlib.Path(\'app/static/logo.png\').write_bytes(bytes.fromhex(\'{PNG.hex()}\'))"'
        self.p.write("assets.toml", decl(extra=f"generate = '''{gen}'''"))

    def tearDown(self) -> None:
        self.p.close()

    def test_generate_then_check(self) -> None:
        code, out = self.p.sdlc("assets", "--check")
        self.assertEqual(code, 1, out)
        self.assertIn("ERROR app/static/logo.png: missing", out)
        code, out = self.p.sdlc("assets")
        self.assertEqual(code, 0, out)
        self.assertIn("made  app/static/logo.png", out)
        self.assertEqual((self.p.root / "app/static/logo.png").read_bytes(), PNG)
        self.assertEqual(self.p.sdlc("assets", "--check")[0], 0)

    def test_a_generator_that_does_not_match_its_hash_fails(self) -> None:
        self.p.write("assets.toml", self.p.read("assets.toml").replace(SHA, "0" * 64))
        code, out = self.p.sdlc("assets")
        self.assertEqual(code, 1)
        self.assertIn(f"produced sha256 {SHA}, not the declared {'0' * 64}", out)

    def fetch(self, body) -> str:
        cfg = config.load(self.p.root)
        opener = mock.Mock()
        opener.open.return_value = body
        with mock.patch("sdlc.assets._opener", return_value=opener):
            return assets.produce(cfg, assets.Asset("vendor/font.bin", SHA, source="https://example.org/font.bin"))

    def test_a_source_is_fetched_and_verified(self) -> None:
        self.assertEqual(self.fetch(io.BytesIO(PNG)), "")
        self.assertEqual((self.p.root / "vendor/font.bin").read_bytes(), PNG)
        (self.p.root / "vendor/font.bin").unlink()
        why = self.fetch(io.BytesIO(b"other bytes"))
        self.assertIn("not the pinned", why)
        self.assertEqual(list((self.p.root / "vendor").iterdir()), [], "a mismatched download is not kept")

    def test_a_broken_download_leaves_nothing_behind(self) -> None:
        import http.client

        class Broken(io.BytesIO):
            def read(self, n=-1):
                raise http.client.IncompleteRead(b"partial")

        why = self.fetch(Broken())
        self.assertIn("fetching https://example.org/font.bin failed", why)
        self.assertEqual(list((self.p.root / "vendor").iterdir()), [])
        cfg = config.load(self.p.root)
        opener = mock.Mock()
        opener.open.side_effect = OSError("connection reset")
        with mock.patch("sdlc.assets._opener", return_value=opener):
            why = assets.produce(cfg, assets.Asset("vendor/font.bin", SHA, source="https://example.org/font.bin"))
        self.assertIn("connection reset", why)
        self.assertEqual(list((self.p.root / "vendor").iterdir()), [])

    def test_a_redirect_off_https_is_refused(self) -> None:
        import urllib.error
        import urllib.request
        h = assets._HttpsOnly()
        req = urllib.request.Request("https://example.org/a")
        with self.assertRaises(urllib.error.URLError):
            h.redirect_request(req, None, 302, "Found", {}, "http://example.org/a")
        self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {}, "https://cdn.example.org/a"))

    def test_a_path_through_a_symlinked_folder_is_refused(self) -> None:
        import os
        import tempfile
        outside = tempfile.mkdtemp()
        os.symlink(outside, self.p.root / "linked")
        cfg = config.load(self.p.root)
        why = assets.produce(cfg, assets.Asset("linked/x.png", SHA, generate="true"))
        self.assertIn("resolves outside the repository", why)

    def test_a_generator_that_hangs_is_stopped(self) -> None:
        cfg = config.load(self.p.root)
        a = assets.Asset("app/static/logo.png", SHA, generate=f'"{sys.executable}" -c "import time; time.sleep(5)"')
        self.assertIn("generate ran longer than 1s", assets.produce(cfg, a, timeout=1))


if __name__ == "__main__":
    unittest.main()
