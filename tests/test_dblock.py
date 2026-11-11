"""Tests for dblock. A local HTTP server (with Range support) stands in for upstream."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shlex
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dblock import cli, compat, store
from dblock.lockfile import Entry, Lockfile
from dblock.recipes import RecipeError, load_recipes, parse_spec

FILES: dict[str, bytes] = {}  # url path -> bytes served


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = FILES.get(self.path)
        if body is None:
            self.send_error(404)
            return
        start = 0
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body) - start))
        self.end_headers()
        self.wfile.write(body[start:])

    def log_message(self, *args):
        pass


def make_tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def recipe_toml(name: str, releases: list[dict], **top) -> str:
    out = [f'name = "{name}"', 'description = "test db"', 'homepage = "http://example.org"',
           'tool = "python"', 'version_command = ["python", "--version"]', 'citation = "Test et al."']
    out += [f"{key} = {json.dumps(value)}" for key, value in top.items()]
    for rel in releases:
        out.append("\n[[releases]]")
        for key, value in rel.items():
            out.append(f"{key} = {json.dumps(value)}")
    return "\n".join(out) + "\n"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FILES.clear()
        self.tmp = Path(tempfile.mkdtemp())
        self.recipes = self.tmp / "recipes"
        self.recipes.mkdir()
        self.lock = self.tmp / "dblock.lock"
        self.store_dir = self.tmp / "store"

    def serve(self, path: str, data: bytes) -> str:
        FILES[path] = data
        return self.base + path

    def write_recipe(self, name: str, releases: list[dict], **top) -> None:
        (self.recipes / f"{name}.toml").write_text(recipe_toml(name, releases, **top), encoding="utf-8")

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        args = list(argv[:1]) + ["--lock", str(self.lock), "--store", str(self.store_dir),
                                 "--recipes", str(self.recipes)] + list(argv[1:])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def simple_db(self, name="toy", version="1", members=None, checksum=True, layout=("toy/a.txt",)):
        members = members or {"toy/a.txt": b"alpha\n", "toy/sub/b.txt": b"bravo" * 100}
        data = make_tar(members)
        url = self.serve(f"/{name}-{version}.tar.gz", data)
        rel = {"version": version, "urls": [url], "filename": f"{name}-{version}.tar.gz",
               "format": "tar.gz", "size": len(data), "layout": list(layout)}
        if checksum:
            rel["checksum"] = "md5:" + hashlib.md5(data).hexdigest()
        return rel, data


class TestRecipesAndSpecs(unittest.TestCase):
    def test_bundled_recipes_load(self):
        recipes = load_recipes()
        for name in ("gtdbtk", "kraken2", "checkm2", "bakta", "bakta-galaxy-test"):
            self.assertIn(name, recipes)
        self.assertEqual(recipes["gtdbtk"].release("r226").tool_versions, ">=2.4.1,<=2.6.1")
        self.assertEqual(recipes["gtdbtk"].release(None).version, "r232")

    def test_unknown_release(self):
        with self.assertRaises(RecipeError):
            load_recipes()["gtdbtk"].release("r1")

    def test_bundled_tool_paths_match_layout(self):
        # Every bundled tool_path must be a folder or file the recipe's layout says exists.
        for recipe in load_recipes().values():
            for rel in recipe.releases:
                if not rel.tool_path:
                    continue
                self.assertTrue(recipe.tool_env, recipe.name)
                if rel.tool_path == ".":
                    continue
                self.assertTrue(any(p.rstrip("/") == rel.tool_path or p.startswith(rel.tool_path + "/")
                                    for p in rel.layout), f"{recipe.name}@{rel.version}: {rel.tool_path}")

    def test_tool_path_must_stay_inside_data(self):
        for bad in ("../outside", "/abs/path"):
            tmp = Path(tempfile.mkdtemp())
            (tmp / "bad.toml").write_text(recipe_toml("bad", [{
                "version": "1", "urls": ["http://x"], "filename": "x.tar.gz", "format": "tar.gz",
                "tool_path": bad}]), encoding="utf-8")
            with self.assertRaises(RecipeError):
                load_recipes(tmp)

    def test_parse_spec(self):
        self.assertEqual(parse_spec("gtdbtk@r232"), ("gtdbtk", "r232"))
        self.assertEqual(parse_spec("kraken2"), ("kraken2", None))
        with self.assertRaises(RecipeError):
            parse_spec("@r1")


class TestCompat(unittest.TestCase):
    def test_satisfies(self):
        self.assertTrue(compat.satisfies("2.5.0", ">=2.4.1,<=2.6.1"))
        self.assertFalse(compat.satisfies("2.7.0", ">=2.4.1,<=2.6.1"))
        self.assertTrue(compat.satisfies("2.7", ">=2.7.0"))
        self.assertTrue(compat.satisfies("1.12.2", ">=1.11"))
        self.assertFalse(compat.satisfies("1.10.4", ">=1.11"))
        self.assertTrue(compat.satisfies("9", ""))

    def test_bad_spec(self):
        with self.assertRaises(compat.SpecError):
            compat.satisfies("1.0", "~=1.0")

    def test_missing_tool(self):
        result = compat.check(("definitely-not-a-tool-xyz", "--version"), r"(\d+)", ">=1")
        self.assertEqual(result.status, "tool-not-found")


class TestLockfile(unittest.TestCase):
    def test_roundtrip(self):
        path = Path(tempfile.mkdtemp()) / "dblock.lock"
        lock = Lockfile(path)
        lock.entries["a-b"] = Entry(name="a-b", release='r"1', recipe_digest="sha256:x", filename="f",
                                    format="tar.gz", urls=["u1", "u2"], files=3)
        lock.save()
        again = Lockfile.load(path)
        self.assertEqual(again.entries["a-b"], lock.entries["a-b"])


class TestFetchVerify(Base):
    def test_full_cycle(self):
        rel, _ = self.simple_db()
        self.write_recipe("toy", [rel])
        self.assertEqual(self.run_cli("add", "toy")[0], 0)
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 0, err)
        entry = Lockfile.load(self.lock).get("toy")
        self.assertEqual(entry.checksum_origin, "upstream-verified")
        self.assertEqual(entry.files, 2)
        self.assertTrue(entry.tree_digest.startswith("sha256:"))
        self.assertFalse((self.store_dir / ".downloads" / "toy-1.tar.gz").exists())  # archive removed

        code, out, _ = self.run_cli("verify", "--full")
        self.assertEqual(code, 0)
        self.assertIn("OK (full", out)

        code, out, _ = self.run_cli("path", "toy")
        self.assertEqual(Path(out.strip()), store.data_dir(self.store_dir, "toy", "1"))

        code, out, _ = self.run_cli("provenance", "--format", "json")
        row = json.loads(out)["databases"][0]
        self.assertEqual(row["release"], "1")
        self.assertEqual(row["citation"], "Test et al.")

        # second fetch is a no-op
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 0)
        self.assertIn("already installed", err)

    def test_verify_detects_changes(self):
        rel, _ = self.simple_db()
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        self.run_cli("fetch")
        data = store.data_dir(self.store_dir, "toy", "1")
        (data / "toy/a.txt").write_bytes(b"ALPHA\n")  # same size, different content
        self.assertEqual(self.run_cli("verify")[0], 0)  # fast mode only checks names and sizes
        code, out, _ = self.run_cli("verify", "--full")
        self.assertEqual(code, 1)
        self.assertIn("content changed", out)
        (data / "toy/extra.txt").write_text("x")
        (data / "toy/sub/b.txt").unlink()
        code, out, _ = self.run_cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("missing", out)
        self.assertIn("unexpected", out)

    def test_upstream_checksum_mismatch(self):
        rel, _ = self.simple_db()
        rel["checksum"] = "md5:" + "0" * 32
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 1)
        self.assertIn("md5 mismatch", err)
        self.assertTrue((self.store_dir / ".downloads" / "toy-1.tar.gz.bad").exists())
        self.assertFalse(Lockfile.load(self.lock).get("toy").fetched)

    def test_no_upstream_checksum_records_first_download(self):
        rel, data = self.simple_db(checksum=False)
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        self.assertEqual(self.run_cli("fetch")[0], 0)
        entry = Lockfile.load(self.lock).get("toy")
        self.assertEqual(entry.checksum_origin, "first-download")
        self.assertEqual(entry.archive_sha256, hashlib.sha256(data).hexdigest())

    def test_silent_upstream_change_is_caught(self):
        rel, _ = self.simple_db(checksum=False)
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        self.run_cli("fetch")
        # Another machine: empty store, same lockfile, but upstream replaced the file (same size).
        new = make_tar({"toy/a.txt": b"omega\n", "toy/sub/b.txt": b"bravo" * 100})
        FILES["/toy-1.tar.gz"] = new
        rel["size"] = len(new)
        self.write_recipe("toy", [rel])
        self.store_dir = self.tmp / "store2"
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 1)
        self.assertIn("differs from the locked archive", err)

    def test_resume_partial_download(self):
        rel, data = self.simple_db()
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        part = self.store_dir / ".downloads" / "toy-1.tar.gz.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(data[: len(data) // 2])
        self.assertEqual(self.run_cli("fetch")[0], 0)
        self.assertEqual(Lockfile.load(self.lock).get("toy").archive_sha256, hashlib.sha256(data).hexdigest())

    def test_mirror_fallback(self):
        rel, _ = self.simple_db()
        rel["urls"] = [self.base + "/missing.tar.gz"] + rel["urls"]
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        cli_download = cli.download

        def no_retry(urls, dest, expected_size=0, retries=3, quiet=False):
            return cli_download(urls, dest, expected_size, retries=1, quiet=quiet)

        cli.download = no_retry
        try:
            code, _, err = self.run_cli("fetch")
        finally:
            cli.download = cli_download
        self.assertEqual(code, 0, err)
        self.assertIn("downloaded from " + rel["urls"][1], err)

    def test_layout_problem_reported(self):
        rel, _ = self.simple_db(layout=("toy/a.txt", "toy/expected.idx"))
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 1)
        self.assertIn("toy/expected.idx", err)

    def test_layout_problem_is_not_installed(self):
        # A layout failure must not be recorded, or the next fetch accepts it.
        rel, _ = self.simple_db(layout=("toy/a.txt", "toy/expected.idx"))
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        self.assertEqual(self.run_cli("fetch")[0], 1)
        self.assertFalse(Lockfile.load(self.lock).get("toy").fetched)
        self.assertFalse((store.install_dir(self.store_dir, "toy", "1") / "manifest.json").exists())
        self.assertFalse(store.data_dir(self.store_dir, "toy", "1").exists())
        self.assertTrue((self.store_dir / ".downloads" / "toy-1.tar.gz.bad").exists())
        self.assertEqual(self.run_cli("path", "toy")[0], 1)
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 1)
        self.assertIn("toy/expected.idx", err)

    def test_status_does_not_claim_files_are_checked(self):
        # status only looks for the manifest; it must not say "installed" for a damaged copy.
        rel, _ = self.simple_db()
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        self.run_cli("fetch")
        (store.data_dir(self.store_dir, "toy", "1") / "toy/a.txt").unlink()
        code, out, err = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertNotIn("installed", out)
        self.assertIn("present (not verified)", out)
        self.assertIn("dblock verify", err)
        self.assertEqual(self.run_cli("verify")[0], 1)

    def test_tree_digest_mismatch_is_not_recorded(self):
        # Fetching on another machine must not overwrite the locked tree digest.
        rel, _ = self.simple_db()
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        self.assertEqual(self.run_cli("fetch")[0], 0)
        lock = Lockfile.load(self.lock)
        lock.get("toy").tree_digest = "sha256:" + "0" * 64
        lock.save()
        self.store_dir = self.tmp / "store2"
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 1)
        self.assertIn("differ from the lockfile digest", err)
        self.assertEqual(Lockfile.load(self.lock).get("toy").tree_digest, "sha256:" + "0" * 64)
        self.assertEqual(self.run_cli("fetch")[0], 1)
        self.assertEqual(self.run_cli("verify")[0], 1)

    def test_repeated_checksum_mismatch_keeps_each_bad_file(self):
        rel, _ = self.simple_db()
        rel["checksum"] = "md5:" + "0" * 32
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        self.assertEqual(self.run_cli("fetch")[0], 1)
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 1, err)
        self.assertIn("md5 mismatch", err)
        downloads = self.store_dir / ".downloads"
        self.assertTrue((downloads / "toy-1.tar.gz.bad").exists())
        self.assertTrue((downloads / "toy-1.tar.gz.bad.1").exists())
        self.assertIn("toy-1.tar.gz.bad.1", err)

    def test_diff_between_releases(self):
        rel1, _ = self.simple_db(version="1")
        rel2, _ = self.simple_db(version="2", members={"toy/a.txt": b"alpha2\n", "toy/c.txt": b"new"})
        self.write_recipe("toy", [rel2, rel1])
        for version in ("1", "2"):
            self.run_cli("add", f"toy@{version}")
            self.assertEqual(self.run_cli("fetch")[0], 0)
        code, out, _ = self.run_cli("diff", "toy", "1", "2")
        self.assertEqual(code, 0)
        self.assertIn("1 added, 1 removed, 1 changed", out)

    def test_text_output_is_ascii(self):
        # Redirected stdout on Windows uses the ANSI code page, so non-ASCII
        # characters would be written in the wrong encoding (or fail).
        rel1, _ = self.simple_db(version="1")
        rel2, _ = self.simple_db(version="2", members={"toy/a.txt": b"alpha2\n", "toy/c.txt": b"new"})
        self.write_recipe("toy", [rel2, rel1])
        for version in ("1", "2"):
            self.run_cli("add", f"toy@{version}")
            self.assertEqual(self.run_cli("fetch")[0], 0)
        code, out, _ = self.run_cli("provenance")
        self.assertEqual(code, 0)
        self.assertTrue(out.isascii(), out)
        code, out, _ = self.run_cli("diff", "toy", "1", "2", "--limit", "0")
        self.assertEqual(code, 0)
        self.assertIn("1 more", out)
        self.assertTrue(out.isascii(), out)

    def test_unsafe_archive_rejected(self):
        rel, _ = self.simple_db(members={"../evil.txt": b"x"}, layout=())
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        code, _, _ = self.run_cli("fetch")
        self.assertNotEqual(code, 0)
        self.assertFalse((self.store_dir / "toy" / "evil.txt").exists())

    def test_check_compat_flags_incompatible_tool(self):
        rel_ok, _ = self.simple_db(version="2")
        rel_ok["tool_versions"] = ">=3.11"
        rel_bad, _ = self.simple_db(version="1")
        rel_bad["tool_versions"] = ">=99"
        self.write_recipe("toy", [rel_ok, rel_bad])
        self.run_cli("add", "toy@2")
        code, out, _ = self.run_cli("check-compat")
        self.assertEqual(code, 0, out)
        self.assertIn("OK (python 3.", out)
        self.run_cli("add", "toy@1")
        code, out, _ = self.run_cli("check-compat")
        self.assertEqual(code, 1)
        self.assertIn("INCOMPATIBLE", out)

    def test_check_compat_strict_requires_ok(self):
        rel_ok, _ = self.simple_db(name="good")
        rel_ok["tool_versions"] = ">=3.11"
        self.write_recipe("good", [rel_ok])
        rel_none, _ = self.simple_db(name="norule")
        self.write_recipe("norule", [rel_none])
        self.run_cli("add", "good")
        code, out, _ = self.run_cli("check-compat", "--strict")
        self.assertEqual(code, 0, out)
        self.run_cli("add", "norule")
        code, out, _ = self.run_cli("check-compat")  # default unchanged: NO-RULE is not a failure
        self.assertEqual(code, 0, out)
        code, out, err = self.run_cli("check-compat", "--strict")
        self.assertEqual(code, 1)
        self.assertIn("norule@1: NO-RULE", out)
        self.assertIn("1 of 2", err)

    def test_check_compat_strict_fails_when_tool_missing(self):
        rel, _ = self.simple_db()
        rel["tool_versions"] = ">=1"
        text = recipe_toml("toy", [rel]).replace('["python", "--version"]', '["dblock-no-such-tool", "--version"]')
        (self.recipes / "toy.toml").write_text(text, encoding="utf-8")
        self.run_cli("add", "toy")
        code, out, _ = self.run_cli("check-compat")
        self.assertEqual(code, 0)
        self.assertIn("TOOL-NOT-FOUND", out)
        self.assertEqual(self.run_cli("check-compat", "--strict")[0], 1)

    def test_unknown_database(self):
        code, _, err = self.run_cli("add", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown database", err)


class TestFreeSpace(Base):
    def setUp(self):
        super().setUp()
        self.free = 0
        self.real_free = cli._free_bytes
        cli._free_bytes = lambda path: self.free

    def tearDown(self):
        cli._free_bytes = self.real_free

    def toy(self, unpacked_size=None):
        rel, data = self.simple_db()
        if unpacked_size is not None:
            rel["unpacked_size"] = unpacked_size
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        return len(data)

    def test_not_enough_space_downloads_nothing(self):
        size = self.toy()
        self.free = 2 * size - 1  # archive + (unknown unpacked size, assumed >= archive)
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 1)
        self.assertIn("not enough free space", err)
        self.assertIn("at least", err)
        self.assertFalse((self.store_dir / ".downloads").exists())
        self.assertFalse(Lockfile.load(self.lock).get("toy").fetched)

    def test_enough_space_fetches(self):
        size = self.toy()
        self.free = 2 * size
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 0, err)

    def test_unpacked_size_from_recipe_is_used(self):
        size = self.toy(unpacked_size=10 * 1024 * 1024)
        self.free = 2 * size + 1024  # enough for the archive twice, not for 10 MB unpacked
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 1)
        self.assertIn("not enough free space", err)
        self.assertNotIn("at least", err)

    def test_partial_download_counts_as_already_used(self):
        size = self.toy()
        part = self.store_dir / ".downloads" / "toy-1.tar.gz.part"
        part.parent.mkdir(parents=True)
        part.write_bytes(FILES["/toy-1.tar.gz"][: size // 2])
        self.free = (size - size // 2) + size  # the rest of the download + unpacked
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 0, err)

    def test_no_space_check_skips_it(self):
        self.toy()
        self.free = 0
        code, _, err = self.run_cli("fetch", "--no-space-check")
        self.assertEqual(code, 0, err)

    def test_unknown_size_skips_check_with_note(self):
        rel, _ = self.simple_db()
        del rel["size"]
        self.write_recipe("toy", [rel])
        self.run_cli("add", "toy")
        self.free = 0
        code, _, err = self.run_cli("fetch")
        self.assertEqual(code, 0, err)
        self.assertIn("free-space check skipped", err)


class TestToolPaths(Base):
    def install(self, name="toy", tool_env="TOY_DB", tool_path="toy", fetch=True):
        rel, _ = self.simple_db(name=name)
        if tool_path:
            rel["tool_path"] = tool_path
        top = {"tool_env": tool_env} if tool_env else {}
        self.write_recipe(name, [rel], **top)
        self.run_cli("add", name)
        if fetch:
            self.assertEqual(self.run_cli("fetch", name)[0], 0)
        return store.data_dir(self.store_dir, name, "1")

    def test_path_tool(self):
        data = self.install()
        code, out, _ = self.run_cli("path", "toy", "--tool")
        self.assertEqual(code, 0)
        self.assertEqual(Path(out.strip()), data / "toy")
        code, out, _ = self.run_cli("path", "toy")  # unchanged without --tool
        self.assertEqual(Path(out.strip()), data)

    def test_path_tool_without_recipe_rule(self):
        self.install(tool_env="", tool_path="")
        code, out, err = self.run_cli("path", "toy", "--tool")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("states no tool path", err)

    def test_path_tool_missing_on_disk(self):
        data = self.install()
        (data / "toy" / "a.txt").unlink()
        (data / "toy" / "sub" / "b.txt").unlink()
        (data / "toy" / "sub").rmdir()
        (data / "toy").rmdir()
        code, out, err = self.run_cli("path", "toy", "--tool")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("not found", err)

    def test_env_exports_quoted_path(self):
        self.store_dir = self.tmp / "store with space"
        data = self.install()
        code, out, err = self.run_cli("env")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("export TOY_DB="), out)
        name, _, value = out.strip()[len("export "):].partition("=")
        self.assertEqual(Path(shlex.split(value)[0]), data / "toy")

    def test_env_not_installed(self):
        self.install(fetch=False)
        code, out, err = self.run_cli("env")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("not installed", err)

    def test_env_skips_recipe_without_variable(self):
        self.install(tool_env="", tool_path="")
        code, out, err = self.run_cli("env")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("no environment variable", err)

    def test_env_conflict_exports_neither(self):
        self.install(name="one")
        self.install(name="two")
        code, out, err = self.run_cli("env")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("TOY_DB", err)


if __name__ == "__main__":
    unittest.main()
