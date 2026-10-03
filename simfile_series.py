#!/usr/bin/env python3
"""Manage the Series field in ITGMania pack.ini files.

Usage:
    simfile_series.py load  <songs_dir> <txt_file>
    simfile_series.py apply <songs_dir> <txt_file>

"load" scans every real song pack in <songs_dir>, reads the Series value from
its pack.ini, and writes a text file containing every group with its packs
indented underneath. Packs without a Series value are listed under
"(No Series)".

"apply" reads that text file back and writes the Series value into each pack's
pack.ini. Packs may be moved between groups by editing the text file.
"""

import os
import sys

SECTION = "Group"
VERSION_KEY = "Version"
KEY = "Series"
NO_SERIES = "(No Series)"
DEFAULT_INI_NAME = "pack.ini"
SIMFILE_EXTENSIONS = (".sm", ".ssc")
DEFAULT_VERSION = 2


class PackIniError(Exception):
    """An existing pack.ini is malformed or ambiguous."""


def is_song_pack(pack_dir):
    """Return True if pack_dir is a real song pack.

    A real song pack contains at least one subdirectory holding a .sm or .ssc
    simfile. Directories without a simfile anywhere below them are not packs
    (e.g. random folders dropped in the songs directory).
    """
    for _root, _dirs, files in os.walk(pack_dir):
        if any(name.lower().endswith(SIMFILE_EXTENSIONS) for name in files):
            return True
    return False


def find_pack_ini(pack_dir):
    """Case-insensitively locate a pack.ini inside pack_dir.

    Returns the real path, or None if the pack has no pack.ini.
    """
    try:
        entries = os.listdir(pack_dir)
    except OSError:
        return None
    for name in entries:
        if name.lower() == DEFAULT_INI_NAME:
            path = os.path.join(pack_dir, name)
            if os.path.isfile(path):
                return path
    return None


def _eol_of(line):
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[-1]
    return None


def _section_name(line):
    """Return a section header's name, or None if the line is not a header.

    Mirrors the engine: a header must start at column 0 with '[' and end with
    ']'; the name between the brackets is used verbatim (not trimmed).
    """
    raw = line.rstrip("\r\n")
    if len(raw) >= 2 and raw[0] == "[" and raw[-1] == "]":
        return raw[1:-1]
    return None


def _is_comment(raw):
    if raw[0] in ";#":
        return True
    if len(raw) > 1 and raw[0] == raw[1] and raw[0] in "/-":
        return True
    return False


def analyze_pack_ini(text):
    """Validate an existing pack.ini and locate its Series key.

    Returns a dict with the split lines, the [Group] section start, the Version
    line index, and the Series line index (or None) plus its value. Raises
    PackIniError if the file is malformed or ambiguous.
    """
    lines = text.splitlines(keepends=True)

    # The engine joins a line ending in '\' with the following line before
    # parsing. That is not supported here: fail loudly instead of editing a
    # line the engine will never see.
    for i, line in enumerate(lines):
        if line.rstrip("\r\n").endswith("\\"):
            raise PackIniError(
                "line continuation (backslash) is not supported (line {})".format(
                    i + 1
                )
            )

    group_starts = [
        i for i, line in enumerate(lines) if _section_name(line) == SECTION
    ]
    if not group_starts:
        raise PackIniError("missing [{}] section".format(SECTION))
    if len(group_starts) > 1:
        raise PackIniError("multiple [{}] sections".format(SECTION))
    start = group_starts[0]

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if _section_name(lines[i]) is not None:
            end = i
            break

    versions = []
    series = []
    for i in range(start + 1, end):
        raw = lines[i].rstrip("\r\n")
        if not raw.strip() or _is_comment(raw):
            continue
        if "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        name = name.strip()
        if name == VERSION_KEY:
            versions.append((i, value.strip()))
        elif name == KEY:
            series.append((i, value.strip()))

    if not versions:
        raise PackIniError("missing {} key".format(VERSION_KEY))
    if len(versions) > 1:
        raise PackIniError("multiple {} keys".format(VERSION_KEY))
    version_idx, version_value = versions[0]
    if version_value == "":
        raise PackIniError("empty {} value".format(VERSION_KEY))

    if len(series) > 1:
        raise PackIniError("multiple {} keys".format(KEY))

    series_idx = None
    series_value = ""
    if series:
        series_idx, series_value = series[0]

    return {
        "lines": lines,
        "group_start": start,
        "version_idx": version_idx,
        "series_idx": series_idx,
        "series_value": series_value,
    }


def _read_text(path):
    with open(
        path, "r", encoding="utf-8-sig", errors="surrogateescape", newline=""
    ) as f:
        return f.read()


def _write_text(path, text):
    with open(
        path, "w", encoding="utf-8", errors="surrogateescape", newline=""
    ) as f:
        f.write(text)


def read_series(ini_path):
    """Return the Series value from a valid pack.ini.

    Raises PackIniError if the file is malformed or ambiguous.
    """
    return analyze_pack_ini(_read_text(ini_path))["series_value"]


def edit_ini_text(text, value):
    """Return text with Series set to value inside [Group].

    The text must already be a valid pack.ini (see analyze_pack_ini).
    """
    info = analyze_pack_ini(text)
    lines = info["lines"]
    series_idx = info["series_idx"]
    eol = _eol_of(lines[info["group_start"]])

    if series_idx is not None:
        series_eol = _eol_of(lines[series_idx]) or eol
        lines[series_idx] = "{0}={1}{2}".format(KEY, value, series_eol)
    else:
        insert_at = info["version_idx"] + 1
        # Never glue the new line onto one that lacks a trailing newline.
        if _eol_of(lines[insert_at - 1]) is None:
            lines[insert_at - 1] += eol
        lines.insert(insert_at, "{0}={1}{2}".format(KEY, value, eol))

    return "".join(lines)


def _is_safe_pack_name(name):
    """Reject names that could escape the songs directory."""
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name:
        return False
    return True


def _representable_series(series):
    """True if a Series value can be written to and read back from the txt."""
    if series != series.strip():
        return False
    if series.startswith("#"):
        return False
    if series == NO_SERIES:
        return False
    return True


def _representable_pack(name):
    """True if a pack directory name can be written to and read back."""
    if name != name.strip():
        return False
    if name.startswith("#"):
        return False
    return True


def load(songs_dir, txt_path):
    try:
        names = sorted(os.listdir(songs_dir), key=str.lower)
    except OSError as e:
        print(
            "error: cannot read songs directory {}: {}".format(songs_dir, e),
            file=sys.stderr,
        )
        return 1

    groups = {}
    errors = []
    for name in names:
        if name.startswith("."):
            continue
        pack_dir = os.path.join(songs_dir, name)
        if not os.path.isdir(pack_dir):
            continue
        if not is_song_pack(pack_dir):
            continue
        ini_path = find_pack_ini(pack_dir)
        if ini_path is None:
            series = ""
        else:
            try:
                series = read_series(ini_path)
            except (OSError, PackIniError) as e:
                errors.append("{}: {}".format(ini_path, e))
                continue
        if not _representable_pack(name):
            errors.append(
                "pack directory name cannot be represented in the groups file: "
                "{!r}".format(name)
            )
            continue
        if not _representable_series(series):
            errors.append(
                "series name cannot be represented in the groups file: "
                "{!r} (pack {!r})".format(series, name)
            )
            continue
        groups.setdefault(series, []).append(name)

    if errors:
        for error in errors:
            print("error: {}".format(error), file=sys.stderr)
        print("aborting; no file was written.", file=sys.stderr)
        return 1

    out = [
        "# Series assignments for pack.ini files.",
        "# Non-indented lines are groups; indented lines are the packs in them.",
        "# Move a pack line to a different group to reassign it.",
        "# Packs with no series belong under " + NO_SERIES + ".",
        "",
    ]
    group_names = sorted((g for g in groups if g != ""), key=str.lower)
    if "" in groups:
        group_names.append("")
    for group in group_names:
        out.append(group if group != "" else NO_SERIES)
        for pack in sorted(groups[group], key=str.lower):
            out.append("\t" + pack)
        out.append("")

    try:
        _write_text(txt_path, "\n".join(out))
    except OSError as e:
        print("error: cannot write {}: {}".format(txt_path, e), file=sys.stderr)
        return 1
    print("wrote {} ({} packs)".format(txt_path, sum(len(v) for v in groups.values())))
    return 0


def parse_txt(txt_path):
    """Parse a groups text file into an ordered list of (series, pack) pairs."""
    entries = []
    seen = {}
    current = None
    for lineno, line in enumerate(_read_text(txt_path).splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if line[0] in " \t":
            if current is None:
                raise ValueError(
                    "line {}: pack listed before any group header".format(lineno)
                )
            dedupe_key = stripped.casefold()
            if dedupe_key in seen:
                raise ValueError(
                    "line {}: duplicate pack '{}' (first seen on line {})".format(
                        lineno, stripped, seen[dedupe_key]
                    )
                )
            seen[dedupe_key] = lineno
            entries.append((current, stripped))
        else:
            current = "" if stripped == NO_SERIES else stripped
    return entries


def apply(songs_dir, txt_path):
    try:
        entries = parse_txt(txt_path)
    except (OSError, ValueError) as e:
        print("error: {}".format(e), file=sys.stderr)
        return 1

    errors = []
    plans = []
    for series, pack in entries:
        if not _is_safe_pack_name(pack):
            errors.append("invalid pack name: {!r}".format(pack))
            continue
        pack_dir = os.path.join(songs_dir, pack)
        if not os.path.isdir(pack_dir):
            errors.append("pack directory not found: {}".format(pack))
            continue
        if not is_song_pack(pack_dir):
            errors.append("not a song pack (no .sm/.ssc found): {}".format(pack))
            continue
        ini_path = find_pack_ini(pack_dir)
        if ini_path is not None:
            try:
                analyze_pack_ini(_read_text(ini_path))
            except (OSError, PackIniError) as e:
                errors.append("{}: {}".format(ini_path, e))
                continue
        plans.append((series, pack_dir, ini_path))

    if errors:
        for error in errors:
            print("error: {}".format(error), file=sys.stderr)
        print("aborting; no files were changed.", file=sys.stderr)
        return 1

    updated = created = unchanged = skipped = 0
    try:
        for series, pack_dir, ini_path in plans:
            if ini_path is None:
                if series == "":
                    # Nothing to clear and no ini to update: don't create a file
                    # just to record an empty series.
                    skipped += 1
                    continue
                ini_path = os.path.join(pack_dir, DEFAULT_INI_NAME)
                _write_text(
                    ini_path,
                    "[{0}]\n{1}={2}\n{3}={4}\n".format(
                        SECTION, VERSION_KEY, DEFAULT_VERSION, KEY, series
                    ),
                )
                created += 1
                continue

            old = _read_text(ini_path)
            new = edit_ini_text(old, series)
            if new != old:
                _write_text(ini_path, new)
                updated += 1
            else:
                unchanged += 1
    except (OSError, PackIniError) as e:
        print("error: {}".format(e), file=sys.stderr)
        print("warning: some files may have been changed.", file=sys.stderr)
        return 1

    print(
        "updated: {}, created: {}, unchanged: {}, skipped: {}".format(
            updated, created, unchanged, skipped
        )
    )
    return 0


def main(argv):
    if len(argv) != 4 or argv[1] not in ("load", "apply"):
        sys.stderr.write(__doc__)
        return 2
    mode, songs_dir, txt_path = argv[1], argv[2], argv[3]
    if not os.path.isdir(songs_dir):
        print("error: songs directory not found: {}".format(songs_dir), file=sys.stderr)
        return 1
    if mode == "load":
        return load(songs_dir, txt_path)
    return apply(songs_dir, txt_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
