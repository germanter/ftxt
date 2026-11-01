import shlex
import sys
from pathlib import Path

ROOT_DIR = Path.cwd().resolve()
FENCE = ">---"
HEADER_PREFIX = "> "

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


def resolve_source_files(source_str: str) -> list[Path]:
    normalized = source_str.replace("\\", "/")
    p = Path(normalized)
    resolved = (p if p.is_absolute() else ROOT_DIR / p).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"path does not exist: {source_str}")

    if resolved.is_file():
        return [resolved]

    if resolved.is_dir():
        files = sorted(f.resolve() for f in resolved.rglob("*") if f.is_file())
        if not files:
            raise FileNotFoundError(f"directory contains no files: {source_str}")
        return files

    raise ValueError(f"unsupported path type: {source_str}")


def collect_payloads(source_args: list[str], exclude: Path) -> list[tuple[str, str]]:
    files: list[Path] = []
    for src in source_args:
        files.extend(resolve_source_files(src))

    payloads: list[tuple[str, str]] = []
    for f in files:
        if f == exclude:
            continue

        try:
            content = f.read_text(encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(f"failed to read '{f}': {exc}") from exc

        content = content.rstrip("\r\n")
        path = rel(f)

        if any(is_fence(line) for line in content.split("\n")):
            raise ValueError(f"'{path}' contains reserved line '{FENCE}'")

        payloads.append((path, content))

    if not payloads:
        raise FileNotFoundError("nothing to write")

    return payloads


def commit_write(target: Path, source_args: list[str]) -> None:
    if not target.parent.is_dir():
        raise FileNotFoundError(f"destination directory does not exist: {rel(target.parent)}")

    payloads = collect_payloads(source_args, target.resolve())

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

    with open(target, "w", encoding="utf-8", newline="\n") as out:
        out.write(render_entries(existing))

    print("roger")


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


def cmd_help() -> None:
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
        "  mkf <name>                  Create indexed .txt file and select it (alias: openfile)\n"
        "  rmf <target>                Delete .txt file, selection unchanged (alias: delfile)\n"
        "  writo <target> [paths...]   Select .txt file (created if missing), optionally write paths\n"
        "  write to <target> [paths..] Same as writo\n"
        "  write <path...>             Write/update paths into the selected .txt file\n"
        "  inspect [target]            List records, selects the file\n"
        "\n"
        "record format:\n"
        "  >---\n"
        "  > main/stuff.js\n"
        "  <content>\n"
        "  >---\n"
        "\n"
        "  help                        Show manual\n"
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
    "writo": cmd_writo,
    "write": cmd_write,
    "inspect": cmd_inspect,
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