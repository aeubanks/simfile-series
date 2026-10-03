#!/usr/bin/env python3
"""Tests for simfile_series.py.

Run from the repository root with either:
    python3 -m unittest discover -s tests -v
    python3 tests/test_simfile_series.py
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simfile_series


def write_file(path, text, newline=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


def read_file(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def group_ini(series, version=True, display="Some Pack", eol="\n"):
    lines = ["[Group]"]
    if version:
        lines.append("Version=1")
    lines.append("DisplayTitle=" + display)
    lines.append("Series=" + series)
    return eol.join(lines) + eol


def run(func, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = func(*args)
    return rc, out.getvalue(), err.getvalue()


def snapshot(root):
    """Return {path: contents} for every file under root."""
    snap = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            snap[path] = read_file(path)
    return snap


class SimfileSeriesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.songs = os.path.join(self._tmp.name, "Songs")
        os.makedirs(self.songs)
        self.txt = os.path.join(self._tmp.name, "groups.txt")

    def tearDown(self):
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------

    def make_pack(
        self,
        name,
        *,
        ini_name=None,
        ini_text=None,
        simfile="song.sm",
        song_subdir="Song",
        has_simfile=True,
    ):
        pack_dir = os.path.join(self.songs, name)
        os.makedirs(pack_dir, exist_ok=True)
        if has_simfile:
            song_dir = os.path.join(pack_dir, song_subdir)
            os.makedirs(song_dir, exist_ok=True)
            write_file(os.path.join(song_dir, simfile), "// fake simfile\n")
        if ini_name is not None:
            write_file(os.path.join(pack_dir, ini_name), ini_text or "")
        return pack_dir

    def ini_path(self, pack_dir, name="pack.ini"):
        return os.path.join(pack_dir, name)

    def load(self):
        rc, out, err = run(simfile_series.load, self.songs, self.txt)
        self.assertEqual(rc, 0, err)
        return read_file(self.txt)

    def apply(self, text):
        write_file(self.txt, text)
        return run(simfile_series.apply, self.songs, self.txt)

    # -- is_song_pack ----------------------------------------------------

    def test_is_song_pack_detects_sm_and_ssc(self):
        self.assertTrue(simfile_series.is_song_pack(self.make_pack("A", simfile="a.sm")))
        self.assertTrue(simfile_series.is_song_pack(self.make_pack("B", simfile="b.ssc")))

    def test_is_song_pack_is_extension_case_insensitive(self):
        pack = self.make_pack("P", has_simfile=False)
        write_file(os.path.join(pack, "Song", "Chart.SSC"), "//")
        self.assertTrue(simfile_series.is_song_pack(pack))

    def test_is_song_pack_finds_nested_simfile(self):
        pack = self.make_pack("P", has_simfile=False)
        write_file(os.path.join(pack, "a", "b", "deep.ssc"), "//")
        self.assertTrue(simfile_series.is_song_pack(pack))

    def test_is_song_pack_false_without_simfile(self):
        pack = self.make_pack("Empty", has_simfile=False)
        write_file(os.path.join(pack, "readme.txt"), "hi")
        self.assertFalse(simfile_series.is_song_pack(pack))

    # -- load ------------------------------------------------------------

    def test_load_groups_packs_and_no_series(self):
        self.make_pack("Alpha", ini_name="pack.ini", ini_text=group_ini("ITL"))
        self.make_pack("Beta", ini_name="pack.ini", ini_text=group_ini("ITL"))
        self.make_pack("Gamma", ini_name="pack.ini", ini_text=group_ini(""))
        self.make_pack("Delta")  # no pack.ini at all
        text = self.load()
        self.assertIn("ITL\n\tAlpha\n\tBeta", text)
        self.assertIn("(No Series)\n\tDelta\n\tGamma", text)

    def test_load_ignores_dirs_without_simfiles(self):
        self.make_pack("Real", ini_name="pack.ini", ini_text=group_ini("G"))
        write_file(os.path.join(self.songs, "Junk", "notes.txt"), "x")
        text = self.load()
        self.assertIn("Real", text)
        self.assertNotIn("Junk", text)

    def test_load_finds_pack_ini_case_insensitively(self):
        self.make_pack("Upper", ini_name="Pack.ini", ini_text=group_ini("G1"))
        self.make_pack("AllUpper", ini_name="PACK.INI", ini_text=group_ini("G2"))
        text = self.load()
        self.assertIn("G1\n\tUpper", text)
        self.assertIn("G2\n\tAllUpper", text)

    def test_load_skips_hidden_dirs(self):
        self.make_pack(".hidden", ini_name="pack.ini", ini_text=group_ini("G"))
        text = self.load()
        self.assertNotIn(".hidden", text)

    def test_load_malformed_pack_ini_aborts(self):
        self.make_pack("Good", ini_name="pack.ini", ini_text=group_ini("G"))
        self.make_pack("Bad", ini_name="pack.ini", ini_text="[Group]\nSeries=X\n")
        rc, out, err = run(simfile_series.load, self.songs, self.txt)
        self.assertEqual(rc, 1)
        self.assertIn("missing Version key", err)
        self.assertFalse(os.path.exists(self.txt))

    def test_load_errors_on_hash_series(self):
        self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("#rock"))
        rc, out, err = run(simfile_series.load, self.songs, self.txt)
        self.assertEqual(rc, 1)
        self.assertIn("cannot be represented", err)
        self.assertFalse(os.path.exists(self.txt))

    def test_load_errors_on_no_series_literal(self):
        self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("(No Series)"))
        rc, out, err = run(simfile_series.load, self.songs, self.txt)
        self.assertEqual(rc, 1)
        self.assertIn("cannot be represented", err)

    def test_load_errors_on_pack_name_with_whitespace(self):
        self.make_pack(" P", ini_name="pack.ini", ini_text=group_ini("G"))
        rc, out, err = run(simfile_series.load, self.songs, self.txt)
        self.assertEqual(rc, 1)
        self.assertIn("cannot be represented", err)

    def test_load_errors_on_hash_pack_name(self):
        self.make_pack("#P", ini_name="pack.ini", ini_text=group_ini("G"))
        rc, out, err = run(simfile_series.load, self.songs, self.txt)
        self.assertEqual(rc, 1)
        self.assertIn("cannot be represented", err)

    # -- read_series / validation ----------------------------------------

    def test_read_series_returns_value(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("ITL"))
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "ITL")

    def test_read_series_no_series_key(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\n")
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "")

    def test_read_series_missing_group_raises(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Other]\nVersion=1\nSeries=Nope\n"
        )
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    def test_read_series_missing_version_raises(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text="[Group]\nSeries=X\n")
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    def test_read_series_empty_version_raises(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=\nSeries=X\n"
        )
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    def test_read_series_multiple_group_raises(self):
        pack = self.make_pack(
            "P",
            ini_name="pack.ini",
            ini_text="[Group]\nVersion=1\n[Group]\nVersion=1\n",
        )
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    def test_read_series_multiple_version_raises(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\nVersion=2\n"
        )
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    def test_read_series_multiple_series_raises(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\nSeries=A\nSeries=B\n"
        )
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    def test_read_series_section_is_case_sensitive(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[group]\nVersion=1\nSeries=ITL\n"
        )
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    def test_read_series_key_is_case_sensitive(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\nseries=ITL\n"
        )
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "")

    def test_read_series_lowercase_version_raises(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nversion=1\nSeries=X\n"
        )
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    def test_read_series_ignores_comment_styles(self):
        text = (
            "[Group]\nVersion=1\n"
            ";Series=A\n#Series=B\n//Series=C\n--Series=D\n"
            "Series=Real\n"
        )
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=text)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "Real")

    def test_read_series_ignores_other_sections(self):
        pack = self.make_pack(
            "P",
            ini_name="pack.ini",
            ini_text="[Group]\nVersion=1\n[Other]\nSeries=Evil\n",
        )
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "")

    def test_read_series_value_with_equals(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\nSeries=A=B\n"
        )
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "A=B")

    def test_read_series_version_with_spaces(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion = 1\nSeries=Old\n"
        )
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "Old")

    def test_read_series_line_continuation_raises(self):
        pack = self.make_pack(
            "P",
            ini_name="pack.ini",
            ini_text="[Group]\nVersion=1\nDisplayTitle=x\\\nSeries=Evil\n",
        )
        with self.assertRaises(simfile_series.PackIniError):
            simfile_series.read_series(self.ini_path(pack))

    # -- apply: editing --------------------------------------------------

    def test_apply_updates_existing_series(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "New")
        self.assertIn("Version=1", read_file(self.ini_path(pack)))

    def test_apply_inserts_series_when_missing(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\nDisplayTitle=P\n"
        )
        self.apply("New\n\tP\n")
        content = read_file(self.ini_path(pack))
        self.assertIn("Series=New", content)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "New")

    def test_apply_creates_pack_ini(self):
        pack = self.make_pack("P")
        self.assertIsNone(simfile_series.find_pack_ini(pack))
        self.apply("New\n\tP\n")
        ini = self.ini_path(pack)
        self.assertTrue(os.path.isfile(ini))
        content = read_file(ini)
        self.assertIn("[Group]", content)
        self.assertIn("Version=2", content)
        self.assertIn("Series=New", content)
        self.assertEqual(simfile_series.read_series(ini), "New")

    def test_apply_preserves_crlf_line_endings(self):
        pack = self.make_pack(
            "P", ini_name="Pack.ini", ini_text=group_ini("Old", eol="\r\n")
        )
        self.apply("New\n\tP\n")
        content = read_file(self.ini_path(pack, "Pack.ini"))
        self.assertIn("Series=New\r\n", content)
        for i, ch in enumerate(content):
            if ch == "\n":
                self.assertEqual(content[i - 1], "\r", "found a bare LF")

    def test_apply_preserves_ini_filename_case(self):
        pack = self.make_pack("P", ini_name="Pack.ini", ini_text=group_ini("Old"))
        self.apply("New\n\tP\n")
        self.assertTrue(os.path.isfile(self.ini_path(pack, "Pack.ini")))
        self.assertFalse(os.path.isfile(self.ini_path(pack, "pack.ini")))

    def test_apply_preserves_other_keys(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        self.apply("New\n\tP\n")
        content = read_file(self.ini_path(pack))
        self.assertIn("DisplayTitle=Some Pack", content)

    def test_apply_no_series_writes_empty_series(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        self.apply("(No Series)\n\tP\n")
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "")

    def test_apply_does_not_create_ini_for_no_series(self):
        pack = self.make_pack("P")  # no pack.ini
        rc, out, err = self.apply("(No Series)\n\tP\n")
        self.assertEqual(rc, 0, err)
        self.assertIsNone(simfile_series.find_pack_ini(pack))
        self.assertIn("skipped: 1", out)

    def test_apply_ignores_comments_and_blank_lines(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        rc, out, err = self.apply("# a comment\n\nNew\n\n\tP\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "New")

    def test_apply_idempotent(self):
        self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        self.apply("New\n\tP\n")
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 0, err)
        self.assertIn("unchanged: 1", out)

    def test_apply_handles_missing_trailing_newline(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\nDisplayTitle=P"
        )
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 0, err)
        content = read_file(self.ini_path(pack))
        self.assertNotIn("DisplayTitle=PSeries", content)
        self.assertIn("Series=New", content)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "New")

    def test_apply_handles_missing_trailing_newline_with_series(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\nSeries=Old"
        )
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 0, err)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "New")

    def test_apply_inserts_after_version_without_trailing_newline(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text="[Group]\nVersion=1")
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 0, err)
        content = read_file(self.ini_path(pack))
        self.assertNotIn("Version=1Series", content)
        self.assertIn("Series=New", content)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "New")

    def test_apply_inserts_after_version_without_trailing_newline_crlf(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text="[Group]\r\nVersion=1")
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 0, err)
        content = read_file(self.ini_path(pack))
        self.assertNotIn("Version=1Series", content)
        self.assertTrue(content.endswith("\r\n"))
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "New")

    def test_apply_preserves_non_utf8_bytes(self):
        pack = self.make_pack("P")
        ini = self.ini_path(pack)
        write_bytes(ini, b"[Group]\nVersion=1\nDisplayTitle=Caf\xe9\nSeries=Old\n")
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 0, err)
        data = read_bytes(ini)
        self.assertIn(b"Caf\xe9", data)
        self.assertNotIn(b"\xef\xbf\xbd", data)
        self.assertIn(b"Series=New", data)

    def test_apply_ignores_series_in_other_sections(self):
        pack = self.make_pack(
            "P",
            ini_name="pack.ini",
            ini_text="[Group]\nVersion=1\n[Other]\nSeries=Evil\n",
        )
        self.apply("New\n\tP\n")
        content = read_file(self.ini_path(pack))
        self.assertIn("[Other]\nSeries=Evil", content)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "New")

    # -- apply: validation / atomicity -----------------------------------

    def test_apply_missing_pack_aborts_without_changes(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        before = snapshot(self.songs)
        rc, out, err = self.apply("New\n\tP\n\tDoesNotExist\n")
        self.assertEqual(rc, 1)
        self.assertIn("not found", err)
        self.assertIn("no files were changed", err)
        self.assertEqual(snapshot(self.songs), before)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "Old")

    def test_apply_non_song_pack_aborts(self):
        write_file(os.path.join(self.songs, "Junk", "notes.txt"), "x")
        before = snapshot(self.songs)
        rc, out, err = self.apply("New\n\tJunk\n")
        self.assertEqual(rc, 1)
        self.assertIn("not a song pack", err)
        self.assertEqual(snapshot(self.songs), before)

    def test_apply_duplicate_pack_aborts(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        before = snapshot(self.songs)
        rc, out, err = self.apply("G1\n\tP\nG2\n\tP\n")
        self.assertEqual(rc, 1)
        self.assertIn("duplicate", err)
        self.assertEqual(snapshot(self.songs), before)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "Old")

    def test_apply_duplicate_pack_case_insensitive_aborts(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        before = snapshot(self.songs)
        rc, out, err = self.apply("G1\n\tP\nG2\n\tp\n")
        self.assertEqual(rc, 1)
        self.assertIn("duplicate", err)
        self.assertEqual(snapshot(self.songs), before)
        self.assertEqual(simfile_series.read_series(self.ini_path(pack)), "Old")

    def test_apply_line_continuation_aborts(self):
        pack = self.make_pack(
            "P",
            ini_name="pack.ini",
            ini_text="[Group]\nVersion=1\nDisplayTitle=x\\\nSeries=Evil\n",
        )
        before = snapshot(self.songs)
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 1)
        self.assertIn("continuation", err)
        self.assertEqual(snapshot(self.songs), before)

    def test_apply_pack_before_header_aborts(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text=group_ini("Old"))
        before = snapshot(self.songs)
        rc, out, err = self.apply("\tP\nG\n")
        self.assertEqual(rc, 1)
        self.assertIn("before any group header", err)
        self.assertEqual(snapshot(self.songs), before)

    def test_apply_missing_group_section_aborts(self):
        pack = self.make_pack("P", ini_name="pack.ini", ini_text="[Other]\nFoo=bar\n")
        before = snapshot(self.songs)
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 1)
        self.assertIn("missing [Group] section", err)
        self.assertEqual(snapshot(self.songs), before)

    def test_apply_missing_version_aborts(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nDisplayTitle=P\n"
        )
        before = snapshot(self.songs)
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 1)
        self.assertIn("missing Version key", err)
        self.assertEqual(snapshot(self.songs), before)

    def test_apply_empty_version_aborts(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=\nSeries=Old\n"
        )
        before = snapshot(self.songs)
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 1)
        self.assertIn("empty Version value", err)
        self.assertEqual(snapshot(self.songs), before)

    def test_apply_multiple_group_sections_aborts(self):
        pack = self.make_pack(
            "P",
            ini_name="pack.ini",
            ini_text="[Group]\nVersion=1\n[Group]\nVersion=1\n",
        )
        before = snapshot(self.songs)
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 1)
        self.assertIn("multiple [Group] sections", err)
        self.assertEqual(snapshot(self.songs), before)

    def test_apply_multiple_series_aborts(self):
        pack = self.make_pack(
            "P", ini_name="pack.ini", ini_text="[Group]\nVersion=1\nSeries=A\nSeries=B\n"
        )
        before = snapshot(self.songs)
        rc, out, err = self.apply("New\n\tP\n")
        self.assertEqual(rc, 1)
        self.assertIn("multiple Series keys", err)
        self.assertEqual(snapshot(self.songs), before)

    def test_apply_invalid_pack_name_aborts(self):
        write_file(os.path.join(self.songs, "P", "Song", "s.sm"), "//")
        rc, out, err = self.apply("New\n\t../Outside\n")
        self.assertEqual(rc, 1)
        self.assertIn("invalid pack name", err)

    def test_apply_absolute_pack_name_aborts(self):
        write_file(os.path.join(self.songs, "P", "Song", "s.sm"), "//")
        rc, out, err = self.apply("New\n\t/etc\n")
        self.assertEqual(rc, 1)
        self.assertIn("invalid pack name", err)

    # -- round trip ------------------------------------------------------

    def test_load_apply_roundtrip_is_stable(self):
        self.make_pack("A", ini_name="pack.ini", ini_text=group_ini("ITL"))
        self.make_pack("B", ini_name="pack.ini", ini_text=group_ini(""))
        self.make_pack("C")  # no pack.ini
        first = self.load()
        rc, out, err = self.apply(first)
        self.assertEqual(rc, 0, err)
        second = self.load()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
