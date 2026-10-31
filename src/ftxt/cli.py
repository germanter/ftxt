import os
import shlex
import sys
from pathlib import Path

ROOT_DIR = Path.cwd().resolve()
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


def resolve_folder_target(name: str) -> Path:
    normalized = name.replace("\\", "/")
    p = Path(normalized)
    if "/" in normalized:
        return (ROOT_DIR / p).resolve()
    return (active_folder / p).resolve()


def resolve_target_file(name: str, must_be_txt: bool = True) -> Path:
    normalized = name.replace("\\", "/")
    p = Path(normalized)

    if must_be_txt:
        if p.suffix and p.suffix != ".txt":
            raise ValueError(f"target is not a .txt file: {name}")
        if not p.suffix:
            normalized += ".txt"
            p = Path(normalized)

    if "/" in normalized:
        return (ROOT_DIR / p).resolve()
    return (active_folder / p).resolve()


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


def is_path_header(line: str) -> bool:
    clean = line.strip().replace("\\", "/")
    if not clean or any(c in clean for c in ' \t":{}()<>;$!'):
        return False

    try:
        target_path = (ROOT_DIR / clean).resolve()
        if target_path.is_file() and ROOT_DIR in target_path.parents:
            return True
    except Exception:
        pass

    parts = clean.split("/")
    if len(parts) > 1 and "." in parts[-1] and not parts[-1].startswith("."):
        return True

    return False


def parse_out_file(target: Path) -> list[tuple[str, str]]:
    if not target.exists():
        raise FileNotFoundError(f"target file not found: {target.name}")

    raw_text = target.read_text(encoding="utf-8")
    if not raw_text.strip():
        return []

    lines = raw_text.splitlines()
    entries: list[tuple[str, list[str]]] = []
    current_path: str | None = None
    current_lines: list[str] = []

    for line in lines:
        trimmed = line.strip()
        if is_path_header(trimmed):
            if current_path is not None:
                entries.append((current_path, current_lines))
            current_path = trimmed.replace("\\", "/")
            current_lines = []
        else:
            if current_path is not None:
                current_lines.append(line)

    if current_path is not None:
        entries.append((current_path, current_lines))

    result: list[tuple[str, str]] = []
    for path_str, body_lines in entries:
        body = "\n".join(body_lines).rstrip("\r\n")
        result.append((path_str, body))

    return result


def resolve_source_files(source_str: str) -> list[Path]:
    normalized = source_str.replace("\\", "/")
    p = Path(normalized)
    resolved = p if p.is_absolute() else (ROOT_DIR / p).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"path does not exist: {source_str}")

    if resolved.is_file():
        return [resolved]

    if resolved.is_dir():
        files = sorted([f for f in resolved.rglob("*") if f.is_file()])
        if not files:
            raise FileNotFoundError(f"directory contains no files: {source_str}")
        return files

    raise ValueError(f"unsupported path type: {source_str}")


def commit_write(target: Path, source_args: list[str]) -> None:
    global active_file

    if not target.parent.exists():
        raise FileNotFoundError(f"destination directory does not exist: {target.parent}")

    target_files: list[Path] = []
    for src in source_args:
        target_files.extend(resolve_source_files(src))

    incoming_payloads: list[tuple[str, str]] = []
    for f in target_files:
        try:
            content = f.read_text(encoding="utf-8")
        except Exception as exc:
            raise RuntimeError(f"failed to read '{f}': {exc}") from exc

        try:
            rel_path = f.relative_to(ROOT_DIR).as_posix()
        except ValueError:
            rel_path = f.as_posix()

        incoming_payloads.append((rel_path, content.rstrip("\r\n")))

    existing_entries: list[tuple[str, str]] = []
    if target.exists() and target.stat().st_size > 0:
        existing_entries = parse_out_file(target)

    entry_index_map = {path: idx for idx, (path, _) in enumerate(existing_entries)}

    for rel_path, content in incoming_payloads:
        if rel_path in entry_index_map:
            idx = entry_index_map[rel_path]
            existing_entries[idx] = (rel_path, content)
        else:
            entry_index_map[rel_path] = len(existing_entries)
            existing_entries.append((rel_path, content))

    with open(target, "w", encoding="utf-8") as out:
        for rel_path, content in existing_entries:
            out.write(f"{rel_path}\n{content}\n\n")

    active_file = target
    print("roger")


def cmd_createfolder(args: list[str]) -> None:
    if len(args) != 1:
        raise ValueError("createfolder requires exactly 1 argument")

    target = resolve_folder_target(args[0])
    final_dir = get_next_available_dir(target)
    final_dir.mkdir(parents=True, exist_ok=False)
    print("roger")


def cmd_selectfolder(args: list[str]) -> None:
    global active_folder

    if len(args) != 1:
        raise ValueError("selectfolder requires exactly 1 argument")

    target = resolve_folder_target(args[0])
    if not target.is_dir():
        raise FileNotFoundError(f"directory not found: {args[0]}")

    active_folder = target
    print("roger")


def cmd_openfile(args: list[str]) -> None:
    global active_file

    if len(args) != 1:
        raise ValueError("openfile requires exactly 1 argument")

    target = resolve_target_file(args[0], must_be_txt=True)
    if not target.parent.exists():
        raise FileNotFoundError(f"parent directory does not exist: {target.parent}")

    final_file = get_next_available_file(target)
    final_file.touch(exist_ok=False)

    active_file = final_file
    print("roger")


def cmd_delfile(args: list[str]) -> None:
    global active_file

    if len(args) != 1:
        raise ValueError("delfile requires exactly 1 argument")

    target = resolve_target_file(args[0], must_be_txt=True)

    if not target.exists():
        raise FileNotFoundError(f"file not found: {args[0]}")
    if target.is_dir():
        raise ValueError(f"refused: target is a directory: {args[0]}")

    target.unlink()
    if active_file == target:
        active_file = None

    print("roger")


def cmd_inspect(args: list[str]) -> None:
    global active_file

    if len(args) > 1:
        raise ValueError("inspect accepts at most 1 argument")

    if len(args) == 1:
        target = resolve_target_file(args[0], must_be_txt=True)
    else:
        if active_file is None:
            raise RuntimeError("no active file. use 'inspect <target>'")
        target = active_file

    entries = parse_out_file(target)
    if not entries:
        raise ValueError(f"file '{target.name}' contains no records")

    active_file = target
    for idx, (path_str, _) in enumerate(entries, 1):
        print(f"{idx}. {path_str}")


def cmd_writo(args: list[str]) -> None:
    global active_file

    if not args:
        raise ValueError("writo requires target file")

    target = resolve_target_file(args[0], must_be_txt=True)
    if not target.parent.exists():
        raise FileNotFoundError(f"parent directory does not exist: {target.parent}")

    if not target.exists():
        target.touch()

    active_file = target

    if len(args) == 1:
        print("roger")
        return

    commit_write(target, args[1:])


def cmd_write(args: list[str]) -> None:
    global active_file

    if not args:
        raise ValueError("missing arguments for write")

    if args[0].lower() == "to":
        cmd_writo(args[1:])
        return

    if active_file is None:
        raise RuntimeError("no active file. use 'writo <target>' or 'openfile'")

    commit_write(active_file, args)


def cmd_help() -> None:
    help_text = (
        "commands:\n"
        "  createfolder <name>         Create directory with auto-indexing (alias: mkdir)\n"
        "  selectfolder <name>         Select active directory (alias: cd)\n"
        "  openfile <name>             Create indexed .txt file\n"
        "  delfile <target>            Delete .txt file (directories forbidden)\n"
        "  writo <target> [paths...]   Select .txt file or write/update files inplace\n"
        "  write to <target> [paths..] Equivalent to writo\n"
        "  write <path...>             Write/update files into current active .txt\n"
        "  inspect [target]            List files contained inside target .txt\n"
        "  help                        Show manual\n"
        "  exit                        Terminate session (alias: quit)"
    )
    print(help_text)


def main() -> None:
    while True:
        try:
            raw = input("ftxt> ").strip()
            if not raw:
                continue

            tokens = parse_cli_input(raw)
            if not tokens:
                continue

            cmd = tokens[0].lower()
            args = tokens[1:]

            if cmd in ("exit", "quit"):
                sys.exit(0)
            elif cmd in ("createfolder", "mkdir"):
                cmd_createfolder(args)
            elif cmd in ("selectfolder", "cd"):
                cmd_selectfolder(args)
            elif cmd in ("openfile", "open"):
                cmd_openfile(args)
            elif cmd == "delfile":
                cmd_delfile(args)
            elif cmd == "writo":
                cmd_writo(args)
            elif cmd == "write":
                cmd_write(args)
            elif cmd == "inspect":
                cmd_inspect(args)
            elif cmd == "help":
                cmd_help()
            else:
                raise ValueError(f"unknown command: {cmd}")

        except (ValueError, FileNotFoundError, RuntimeError) as err:
            print(f"fail: {err}")
        except (KeyboardInterrupt, EOFError):
            print("\nroger")
            sys.exit(0)


if __name__ == "__main__":
    main()