import codecs
import os
import re
import shlex
import sys
from pathlib import Path

ROOT_DIR = Path.cwd().resolve()
FENCE = ">---"
HEADER_PREFIX = "> "
IGNORE_KEYWORD = "*ignore"
SCAN_KEY = "*scan"
SNIFF_BYTES = 8192

active_folder: Path = ROOT_DIR
active_file: Path | None = None


def parse_cli_input(raw: str) -> list[str]:
    raw_tokens = shlex.split(raw, posix=False)
    cleaned = []
    for t in raw_tokens:
        if len(t) >= 2 and ((t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'"))):
            cleaned.append(t[1:-1])
        else:
            cleaned.append(t)
    return cleaned


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def is_inside_root(path: Path) -> bool:
    return path == ROOT_DIR or ROOT_DIR in path.parents


def resolve_folder(name: str) -> Path:
    cleaned = name.replace("\\", "/").strip().strip("/")
    target = (ROOT_DIR / cleaned).resolve()
    if not is_inside_root(target):
        raise ValueError(f"path is outside root: {name}")
    return target


def locate_file(name: str) -> tuple[Path, Path]:
    cleaned = name.replace("\\", "/").strip().strip("/")
    p = Path(cleaned)
    if not cleaned or p.name in ("", ".", ".."):
        raise ValueError(f"invalid file name: {name}")
    if "*" in cleaned:
        raise ValueError(f"invalid file name: {name}")
    if p.suffix and p.suffix != ".txt":
        raise ValueError(f"target is not a .txt file: {name}")

    file_name = p.name if p.suffix else p.name + ".txt"
    if "/" in cleaned:
        folder = resolve_folder(p.parent.as_posix())
    else:
        folder = active_folder
    return folder, folder / file_name


def select(folder: Path, file: Path | None = None) -> None:
    global active_folder, active_file
    active_folder = folder
    if file is not None:
        active_file = file


def get_next_available_dir(base_dir: Path) -> Path:
    if not base_dir.exists():
        return base_dir
    idx = 1
    while True:
        candidate = base_dir.parent / f"{base_dir.name}_{idx}"
        if not candidate.exists():
            return candidate
        idx += 1


def get_next_available_file(base_file: Path) -> Path:
    if not base_file.exists():
        return base_file
    stem = base_file.stem
    idx = 1
    while True:
        candidate = base_file.parent / f"{stem}_{idx}.txt"
        if not candidate.exists():
            return candidate
        idx += 1


def is_fence(line: str) -> bool:
    return line.rstrip() == FENCE


def render_entries(entries: list[tuple[str, str]]) -> str:
    blocks = [f"{FENCE}\n{HEADER_PREFIX}{path}\n{content}\n{FENCE}" for path, content in entries]
    return "\n\n".join(blocks) + "\n"


def parse_out_file(target: Path) -> list[tuple[str, str]]:
    if not target.exists():
        raise FileNotFoundError(f"target file not found: {target.name}")

    text = target.read_text(encoding="utf-8")
    if not text.strip():
        return []

    lines = text.split("\n")
    total = len(lines)
    entries: list[tuple[str, str]] = []
    i = 0

    while i < total:
        if not is_fence(lines[i]):
            i += 1
            continue

        if i + 1 >= total or is_fence(lines[i + 1]) or not lines[i + 1].startswith(">"):
            raise ValueError(f"corrupt record header at line {i + 1}")

        path = lines[i + 1][1:].strip()
        if not path:
            raise ValueError(f"empty record path at line {i + 2}")

        end = i + 2
        while end < total and not is_fence(lines[end]):
            end += 1
        if end >= total:
            raise ValueError(f"unterminated record: {path}")

        body = "\n".join(lines[i + 2:end]).rstrip("\r\n")
        entries.append((path, body))
        i = end + 1

    return entries


def fold(name: str) -> str:
    return name.casefold() if os.name == "nt" else name


IGNORE_KEYWORDS: dict[str, set[str]] = {
    "*ignore": set(),
    "*ignore-all": {"git", "ftxt"},
    "*ignorex": {"git", "ftxt"},
    "*ignore-i": {"git"},
    "*ignore-f": {"ftxt"},
}
RULE_FILES = (("git", ".gitignore"), ("ftxt", ".ftxtignore"))


def split_ignore(args: list[str]) -> tuple[list[str], list[str], set[str]]:
    start = next((i for i, a in enumerate(args) if a.lower() in IGNORE_KEYWORDS), None)
    if start is None:
        return args, [], set()

    names: list[str] = []
    modes: set[str] = set()
    for a in args[start:]:
        key = a.lower()
        if key in IGNORE_KEYWORDS:
            modes |= IGNORE_KEYWORDS[key]
        else:
            names.append(a)

    if not names and not modes:
        raise ValueError(f"'{IGNORE_KEYWORD}' needs at least one name")
    return args[:start], names, modes


def translate_segment(seg: str) -> str:
    out: list[str] = []
    i, n = 0, len(seg)
    while i < n:
        c = seg[i]
        if c == "\\" and i + 1 < n:
            out.append(re.escape(seg[i + 1]))
            i += 2
        elif c == "*":
            while i < n and seg[i] == "*":
                i += 1
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and seg[j] in "!^":
                j += 1
            if j < n and seg[j] == "]":
                j += 1
            while j < n and seg[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
                i += 1
                continue
            stuff = seg[i + 1:j]
            neg = stuff[:1] in ("!", "^")
            if neg:
                stuff = stuff[1:]
            stuff = stuff.replace("\\", "\\\\").replace("[", "\\[")
            if stuff.startswith("]"):
                stuff = "\\" + stuff
            out.append("[" + ("^" if neg else "") + stuff + "]")
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def glob_to_regex(glob: str) -> str:
    segs = glob.split("/")
    n = len(segs)
    out: list[str] = []
    for i, seg in enumerate(segs):
        last = i == n - 1
        if seg == "**":
            out.append(".+" if last else "(?:.*/)?")
        else:
            out.append(translate_segment(seg))
            if not last:
                out.append("/")
    return "".join(out)


def parse_ignore_rules(lines: list[str]) -> list[tuple[re.Pattern, bool, bool]]:
    """gitignore syntax -> [(regex, negated, dir_only)]. Duplicates keep only their last
    occurrence (never changes the result, since the last matching rule wins)."""
    flags = re.IGNORECASE if os.name == "nt" else 0
    parsed: list[tuple[re.Pattern, bool, bool]] = []

    for raw in lines:
        line = raw.rstrip("\r\n")
        while line.endswith(" ") and not line.endswith("\\ "):
            line = line[:-1]
        if not line or line.startswith("#"):
            continue

        negated = line.startswith("!")
        if negated:
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        anchored = "/" in line
        line = line.lstrip("/")
        if not line:
            continue

        full = ("^" if anchored else "^(?:.*/)?") + glob_to_regex(line) + "$"
        try:
            parsed.append((re.compile(full, flags), negated, dir_only))
        except re.error:
            continue

    seen: set[tuple[str, bool, bool]] = set()
    rules: list[tuple[re.Pattern, bool, bool]] = []
    for rule in reversed(parsed):
        key = (rule[0].pattern, rule[1], rule[2])
        if key not in seen:
            seen.add(key)
            rules.append(rule)
    rules.reverse()
    return rules


def load_rule_lines(modes: set[str]) -> list[str]:
    lines: list[str] = []
    found = 0
    for mode, file_name in RULE_FILES:
        if mode not in modes:
            continue
        f = ROOT_DIR / file_name
        if f.is_file():
            found += 1
            lines.extend(f.read_text(encoding="utf-8-sig", errors="replace").split("\n"))
        elif len(modes) == 1:
            raise FileNotFoundError(f"{file_name} not found in root")
    if not found:
        raise FileNotFoundError("no .gitignore or .ftxtignore found in root")
    # git itself never tracks .git, so git modes skip it too
    if "git" in modes:
        lines.insert(0, ".git")
    return lines


def build_ignore_matcher(items: list[str], modes: set[str] | None = None):
    names: set[str] = set()
    paths: list[Path] = []
    for item in items:
        c = item.replace("\\", "/").strip().strip("/")
        if c.startswith("./"):
            c = c[2:]
        if not c or c == ".":
            raise ValueError(f"invalid ignore entry: {item}")
        if "/" in c:
            paths.append((ROOT_DIR / c).resolve())
        else:
            names.add(fold(c))

    rules = parse_ignore_rules(load_rule_lines(modes)) if modes else []
    dir_memo: dict[str, bool] = {}

    def rules_ignore(rel_path: str, is_dir: bool) -> bool:
        for regex, negated, dir_only in reversed(rules):
            if dir_only and not is_dir:
                continue
            if regex.match(rel_path):
                return not negated
        return False

    def dir_ignored(rel_dir: str) -> bool:
        # a directory is ignored if it, or any parent, is (children of an ignored dir can't be re-included)
        if rel_dir not in dir_memo:
            parent = rel_dir.rpartition("/")[0]
            dir_memo[rel_dir] = (bool(parent) and dir_ignored(parent)) or rules_ignore(rel_dir, True)
        return dir_memo[rel_dir]

    def is_ignored(path: Path, is_dir: bool = False) -> bool:
        try:
            parts = path.relative_to(ROOT_DIR).parts
            inside_root = True
        except ValueError:
            parts = (path.name,)
            inside_root = False

        if any(fold(part) in names for part in parts):
            return True
        if any(path == ip or ip in path.parents for ip in paths):
            return True

        if rules and inside_root and parts:
            parent = "/".join(parts[:-1])
            if parent and dir_ignored(parent):
                return True
            return rules_ignore("/".join(parts), is_dir)
        return False

    return is_ignored


def read_text_if_text(f: Path) -> str | None:
    """Content sniffing: null byte check + UTF-8 decode check. None = binary/unreadable."""
    try:
        with open(f, "rb") as fh:
            head = fh.read(SNIFF_BYTES)
        if b"\x00" in head:
            return None
        decoder = codecs.getincrementaldecoder("utf-8")()
        decoder.decode(head, final=len(head) < SNIFF_BYTES)
        return f.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def source_to_path(source_str: str) -> Path:
    p = Path(source_str.replace("\\", "/"))
    return (p if p.is_absolute() else ROOT_DIR / p).resolve()


def resolve_source_files(source_str: str, is_ignored) -> list[Path]:
    resolved = source_to_path(source_str)

    if not resolved.exists():
        raise FileNotFoundError(f"path does not exist: {source_str}")

    if resolved.is_file():
        return [resolved]

    if resolved.is_dir():
        files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(resolved):
            base = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not is_ignored(base / d, True)]
            for fn in filenames:
                fp = base / fn
                if not is_ignored(fp):
                    files.append(fp.resolve())
        files.sort()
        return files

    raise ValueError(f"unsupported path type: {source_str}")


def build_scan(is_ignored, exclude: Path | None = None) -> str:
    """Tree x-ray of the whole root. Ignored entries are left out, folders first, A-Z."""
    lines = [(ROOT_DIR.name or "/") + "/"]

    def walk(folder: Path, depth: int) -> None:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return

        dirs: list[str] = []
        files: list[str] = []
        for entry in entries:
            p = Path(entry.path)
            try:
                entry_is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                entry_is_dir = False

            if entry_is_dir:
                if not is_ignored(p, True):
                    dirs.append(entry.name)
            elif p != exclude and not is_ignored(p):
                files.append(entry.name)

        pad = "  " * depth
        for name in sorted(dirs, key=str.casefold):
            lines.append(f"{pad}{name}/")
            walk(folder / name, depth + 1)
        for name in sorted(files, key=str.casefold):
            lines.append(f"{pad}{name}")

    walk(ROOT_DIR, 1)
    return "\n".join(lines)


def collect_payloads(source_args: list[str], is_ignored, exclude: Path, allow_empty: bool = False) -> list[tuple[str, str]]:
    files: list[Path] = []
    for src in source_args:
        files.extend(resolve_source_files(src, is_ignored))

    # single explicit file -> errors are fatal; folder or multiple sources (batch) -> skip and continue
    single = len(source_args) == 1 and source_to_path(source_args[0]).is_file()

    payloads: list[tuple[str, str]] = []
    skipped = 0
    for f in files:
        if f == exclude or is_ignored(f):
            continue

        content = read_text_if_text(f)
        if content is None:
            skipped += 1
            continue

        content = content.rstrip("\r\n")
        path = rel(f)

        if path == SCAN_KEY:
            if single:
                raise ValueError(f"'{path}' is a reserved record name")
            print(f"skipped {path} for using reserved record name")
            continue

        if any(is_fence(line) for line in content.split("\n")):
            if single:
                raise ValueError(f"'{path}' contains reserved line '{FENCE}'")
            print(f"skipped {path} for containing reserved line '{FENCE}'")
            continue

        payloads.append((path, content))

    if skipped:
        print(f"skipped {skipped} binary/unreadable file(s)")

    if not payloads and not allow_empty:
        raise FileNotFoundError("nothing to write")

    return payloads


def commit_write(target: Path, source_args: list[str]) -> None:
    if not target.parent.is_dir():
        raise FileNotFoundError(f"destination directory does not exist: {rel(target.parent)}")

    # '*scan' can sit anywhere in the arguments
    scan = any(a.lower() == SCAN_KEY for a in source_args)
    args = [a for a in source_args if a.lower() != SCAN_KEY]

    sources, ignore_items, modes = split_ignore(args)
    if not sources and not scan:
        raise ValueError(f"no source paths given before '{IGNORE_KEYWORD}'")

    is_ignored = build_ignore_matcher(ignore_items, modes)
    payloads = collect_payloads(sources, is_ignored, target.resolve(), allow_empty=scan)
    scan_text = build_scan(is_ignored, target.resolve()) if scan else None

    existing: list[tuple[str, str]] = []
    if target.exists() and target.read_text(encoding="utf-8").strip():
        existing = parse_out_file(target)
        if not existing:
            raise ValueError(f"refused: '{target.name}' has content but no valid records")

    index_map = {path: idx for idx, (path, _) in enumerate(existing)}

    for path, content in payloads:
        if path in index_map:
            existing[index_map[path]] = (path, content)
        else:
            index_map[path] = len(existing)
            existing.append((path, content))

    if scan_text is not None:
        # the scan record is replaced if present and always goes first
        existing = [e for e in existing if e[0] != SCAN_KEY]
        existing.insert(0, (SCAN_KEY, scan_text))

    with open(target, "w", encoding="utf-8", newline="\n") as out:
        out.write(render_entries(existing))

    print("roger")


def cmd_scan(args: list[str]) -> None:
    sources, ignore_items, modes = split_ignore(args)
    if len(sources) > 1 or any(s != "." for s in sources):
        raise ValueError("*scan always covers the whole root: use '*scan' or '*scan .'")

    print(build_scan(build_ignore_matcher(ignore_items, modes)))


def cmd_mkdirc(args: list[str]) -> None:
    if len(args) != 1:
        raise ValueError("mkdirc requires exactly 1 argument")

    target = resolve_folder(args[0])
    if target == ROOT_DIR:
        raise ValueError(f"invalid folder name: {args[0]}")

    final_dir = get_next_available_dir(target)
    final_dir.mkdir(parents=True, exist_ok=False)
    print("roger")


def cmd_cd(args: list[str]) -> None:
    if len(args) != 1:
        raise ValueError("cd requires exactly 1 argument")

    target = resolve_folder(args[0])
    if not target.is_dir():
        raise FileNotFoundError(f"directory not found: {args[0]}")

    select(target)
    print("roger")


def cmd_mkf(args: list[str]) -> None:
    if len(args) != 1:
        raise ValueError("mkf requires exactly 1 argument")

    folder, target = locate_file(args[0])
    if not folder.is_dir():
        raise FileNotFoundError(f"directory not found: {rel(folder)}")

    final_file = get_next_available_file(target)
    final_file.touch(exist_ok=False)

    select(folder, final_file)
    print("roger")


def cmd_delfile(args: list[str]) -> None:
    global active_file

    if len(args) != 1:
        raise ValueError("delfile requires exactly 1 argument")

    _, target = locate_file(args[0])

    if not target.exists():
        raise FileNotFoundError(f"file not found: {rel(target)}")
    if target.is_dir():
        raise ValueError(f"refused: target is a directory: {rel(target)}")

    target.unlink()
    if active_file == target:
        active_file = None

    print("roger")


def cmd_empty(args: list[str]) -> None:
    # destructive: explicit target required, never touches folders, only valid ftxt out files
    if len(args) != 1:
        raise ValueError("empty requires exactly 1 argument")

    folder, target = locate_file(args[0])

    if target.is_dir():
        raise ValueError(f"refused: target is a directory: {rel(target)}")
    if not target.is_file():
        raise FileNotFoundError(f"file not found: {rel(target)}")

    text = target.read_text(encoding="utf-8")
    if text.strip():
        try:
            entries = parse_out_file(target)
        except ValueError as exc:
            raise ValueError(f"refused: '{rel(target)}' is not a valid out file ({exc})") from exc
        if not entries:
            raise ValueError(f"refused: '{rel(target)}' is not a valid out file (no records)")

    with open(target, "w", encoding="utf-8", newline="\n"):
        pass

    select(folder, target)
    print("roger")


def cmd_inspect(args: list[str]) -> None:
    if len(args) > 1:
        raise ValueError("inspect accepts at most 1 argument")

    if args:
        folder, target = locate_file(args[0])
    else:
        if active_file is None:
            raise RuntimeError("no active file. use 'inspect <target>'")
        folder, target = active_file.parent, active_file

    entries = parse_out_file(target)
    if not entries:
        raise ValueError(f"file '{target.name}' contains no records")

    select(folder, target)
    for idx, (path_str, _) in enumerate(entries, 1):
        print(f"{idx}. {path_str}")


def cmd_writo(args: list[str]) -> None:
    if not args:
        raise ValueError("writo requires target file")

    folder, target = locate_file(args[0])
    if not folder.is_dir():
        raise FileNotFoundError(f"directory not found: {rel(folder)}")

    if len(args) > 1:
        commit_write(target, args[1:])
        select(folder, target)
        return

    if not target.exists():
        target.touch()

    select(folder, target)
    print("roger")


def cmd_write(args: list[str]) -> None:
    if not args:
        raise ValueError("missing arguments for write")

    if args[0].lower() == "to":
        cmd_writo(args[1:])
        return

    if active_file is None:
        raise RuntimeError("no active file. use 'writo <target>' or 'mkf <name>'")

    commit_write(active_file, args)


def cmd_clear(args: list[str]) -> None:
    if args:
        raise ValueError("clear takes no arguments")

    os.system("cls" if os.name == "nt" else "clear")


def cmd_help() -> None:
    help_text = (
        "  cd <folder>                 Select folder, 'cd .' returns to root (alias: selectfolder)\n"
        "  mkdirc <folder>             Create folder from root, auto-indexed, selection unchanged\n"
        "                              (aliases: mkdir, openfolder, createfolder)\n"
        "  mkf <name>                  Create indexed .txt file and select it (aliases: openfile, open)\n"
        "  rmf <target>                Delete .txt file, selection unchanged (alias: delfile)\n"
        "  empty <target>              Empty an out .txt file (keeps the file, never touches folders)\n"
        "                              (aliases: trunc, truncate)\n"
        "  writo <target> [paths...]   Select .txt file (created if missing), optionally write paths\n"
        "  write to <target> [paths..] Same as writo\n"
        "  write <path...>             Write/update paths into the selected .txt file\n"
        "  ... *ignore <names...>      Append to any write: skip these files/folders (by name or path)\n"
        "                              binary / non-UTF-8 files are always skipped automatically\n"
        "                              in batch writes (folder / many sources) files containing '>---' are skipped\n"
        "  ... *ignore-all (*ignorex)  Skip by root .gitignore + .ftxtignore rules, names may follow\n"
        "  ... *ignore-i / *ignore-f   Only .gitignore / only .ftxtignore\n"
        "  ... *scan                   Append to any write: root tree goes in as record '*scan', always first\n"
        "  inspect [target]            List records, selects the file\n"
        "  *scan [.]                   Print a tree x-ray of the whole root (takes *ignore keywords)\n"
        "  clear                       Clear the terminal screen (alias: cls)\n"
        "  help                        Show command list\n"
        "  fullhelp                    Show full manual (rules, record format)\n"
        "  exit                        Terminate session (alias: quit)"
    )
    print(help_text)


def cmd_fullhelp() -> None:
    help_text = (
        "rules:\n"
        "  every path resolves from the root (where ftxt was started)\n"
        "  a file name containing '/' ignores the selected folder, selects its parent folder\n"
        "  e.g. writo out/out1 main/a.js  selects folder 'out' and file 'out1.txt'\n"
        "\n"
        "folders:\n"
        "  cd <folder>                 Select folder, 'cd .' returns to root (alias: selectfolder)\n"
        "  mkdirc <folder>             Create folder from root, auto-indexed, selection unchanged\n"
        "                              (aliases: mkdir, openfolder, createfolder)\n"
        "\n"
        "files:\n"
        "  mkf <name>                  Create indexed .txt file and select it (aliases: openfile, open)\n"
        "  rmf <target>                Delete .txt file, selection unchanged (alias: delfile)\n"
        "  empty <target>              Empty an out .txt file (keeps the file, never touches folders)\n"
        "                              (aliases: trunc, truncate)\n"
        "  writo <target> [paths...]   Select .txt file (created if missing), optionally write paths\n"
        "  write to <target> [paths..] Same as writo\n"
        "  write <path...>             Write/update paths into the selected .txt file\n"
        "  ... *ignore <names...>      Append to any write: skip these files/folders (by name or path)\n"
        "                              binary / non-UTF-8 files are always skipped automatically\n"
        "                              in batch writes (folder / many sources) files containing '>---' are skipped\n"
        "  ... *ignore-all (*ignorex)  Skip by root .gitignore + .ftxtignore rules, names may follow\n"
        "  ... *ignore-i / *ignore-f   Only .gitignore / only .ftxtignore\n"
        "  ... *scan                   Append to any write: root tree goes in as record '*scan', always first\n"
        "  inspect [target]            List records, selects the file\n"
        "  *scan [.]                   Print a tree x-ray of the whole root (takes *ignore keywords)\n"
        "\n"
        "terminal:\n"
        "  clear                       Clear the terminal screen (alias: cls)\n"
        "\n"
        "record format:\n"
        "  >---\n"
        "  > main/stuff.js\n"
        "  <content>\n"
        "  >---\n"
        "\n"
        "  help                        Show command list\n"
        "  fullhelp                    Show this manual\n"
        "  exit                        Terminate session (alias: quit)"
    )
    print(help_text)


def build_prompt() -> str:
    file_label = rel(active_file) if active_file else "-"
    return f"ftxt [{rel(active_folder)} | {file_label}]> "


COMMANDS = {
    "createfolder": cmd_mkdirc,
    "mkdir": cmd_mkdirc,
    "mkdirc": cmd_mkdirc,
    "openfolder": cmd_mkdirc,
    "selectfolder": cmd_cd,
    "cd": cmd_cd,
    "openfile": cmd_mkf,
    "open": cmd_mkf,
    "mkf": cmd_mkf,
    "delfile": cmd_delfile,
    "rmf": cmd_delfile,
    "empty": cmd_empty,
    "trunc": cmd_empty,
    "truncate": cmd_empty,
    "writo": cmd_writo,
    SCAN_KEY: cmd_scan,
    "write": cmd_write,
    "inspect": cmd_inspect,
    "clear": cmd_clear,
    "cls": cmd_clear,
}


def main() -> None:
    while True:
        try:
            raw = input(build_prompt()).strip()
            if not raw:
                continue

            tokens = parse_cli_input(raw)
            if not tokens:
                continue

            cmd = tokens[0].lower()
            args = tokens[1:]

            if cmd in ("exit", "quit"):
                sys.exit(0)
            elif cmd == "help":
                cmd_help()
            elif cmd == "fullhelp":
                cmd_fullhelp()
            elif cmd in COMMANDS:
                COMMANDS[cmd](args)
            else:
                raise ValueError(f"unknown command: {cmd}")

        except (ValueError, FileNotFoundError, RuntimeError, OSError) as err:
            print(f"fail: {err}")
        except (KeyboardInterrupt, EOFError):
            print("\nroger")
            sys.exit(0)


if __name__ == "__main__":
    main()