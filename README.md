# ftxt

Strict, minimal CLI codebase-to-text packaging tool.

## Installation

```bash
pip install ftxt
```

Needs Python 3.10 or newer. Works on Windows, macOS and Linux. No other dependencies.

## What it does

ftxt packs files from your project into one plain `.txt` file. Every file becomes a record with its relative path on top and its content below, so the whole codebase ends up in a single readable blob. Handy for pasting a project into an LLM chat, sharing it, or just keeping a snapshot.

It is an interactive shell. You start it in your project root, then type commands. Nothing runs until you say so, and nothing outside your root gets touched.

A few things it cares about:

* Strict. Weird input gets a clear `fail: ...` message instead of a silent guess.
* Safe. It never deletes folders, ever. It only deletes or empties single `.txt` files, and only the right kind.
* Quiet. Success prints `roger`. That's it.

## Quick start

```bash
cd my-project
ftxt
```

```
ftxt [. | -]> writo out . *ignorex
skipped 12 binary/unreadable file(s)
roger
ftxt [. | out.txt]> inspect
1. README.md
2. src/app.py
3. src/utils.py
```

That packed every text file in the project into `out.txt`, skipping everything listed in your `.gitignore` and `.ftxtignore`, and quietly skipping binaries.

The prompt always shows where you are: `ftxt [selected folder | selected file]>`. A `-` means nothing is selected yet.

## The root and the selection

When you start ftxt, the current directory becomes the **root**. This matters:

* Every path you type resolves from the root, not from the selected folder.
* ftxt will not let folder paths leave the root (`path is outside root`).
* The records inside your out file store paths relative to the root, with forward slashes, on every OS.

There are two things you can have selected: a **folder** and a **file**. A plain file name (no `/`) lands in the selected folder. A name that contains `/` ignores the selected folder, resolves from the root, and selects its parent folder.

```
writo out/out1 src
```

This selects folder `out` and file `out1.txt`, whatever was selected before.

Target files are always `.txt`. If you leave the extension off, `.txt` is added. Any other extension fails with `target is not a .txt file`.

## Commands

| Command | Aliases | What it does |
|---|---|---|
| `cd <folder>` | `selectfolder` | Select a folder. `cd .` goes back to the root |
| `mkdirc <folder>` | `mkdir`, `openfolder`, `createfolder` | Create a folder from the root. Auto-indexed, selection unchanged |
| `mkf <name>` | `openfile`, `open` | Create a new indexed `.txt` file and select it |
| `rmf <target>` | `delfile` | Delete one `.txt` file. Selection unchanged |
| `empty <target>` | `trunc`, `truncate` | Empty an out file. The file stays, content goes |
| `writo <target> [paths...]` | `write to <target> [paths...]` | Select a `.txt` file (created if missing), optionally write paths into it |
| `write <paths...>` | | Write or update paths in the selected file |
| `inspect [target]` | | List the records in a file and select it |
| `clear` | `cls` | Clear the terminal |
| `help` | | Short command list |
| `fullhelp` | | Full manual |
| `exit` | `quit` | End the session. Ctrl+C and Ctrl+D also work |

Command names are case-insensitive. Paths with spaces need quotes, single or double: `writo out "my folder"`.

### Auto-indexing

`mkdirc` and `mkf` never overwrite anything. If the name is taken, they add a number:

```
mkdirc out     ->  out/
mkdirc out     ->  out_1/
mkf notes      ->  notes.txt
mkf notes      ->  notes_1.txt
```

`writo` is different. It reuses the file if it already exists, which is what you want when you refresh a snapshot.

## Writing

```
writo out .                      pack the whole root into out.txt
writo out src docs/guide.md      pack a folder and a single file
writo out/snapshot .             same idea, but into the out folder
write src                        add src to the selected file
```

What a source can be:

* A file, packed as one record.
* A folder, packed recursively (every file inside, sorted by path).

Good to know:

* **Updating is in place.** If a path is already in the out file, its record is replaced where it sits. New paths go at the end. Run the same write twice and you get the same file, not duplicates.
* **The out file never packs itself.** The file you are writing to is always left out of its own content.
* **Failed writes change nothing.** Everything is collected and checked first. If something fails, the out file stays exactly as it was.
* **ftxt won't clobber random files.** If the target already has content that is not a valid ftxt record file, the write is refused (`has content but no valid records`). A half-broken record file gets a specific error too, like `corrupt record header` or `unterminated record`.
* Line endings are normalized to `\n`, and trailing blank lines of each file are trimmed.

## Record format

```
>---
> src/app.py
print("hello")
>---

>---
> README.md
# My project
>---
```

Each record is a fence line `>---`, a header line `> <relative path>`, the file content, and a closing fence. Records are separated by one blank line.

The line `>---` is reserved. A file that contains a line made of exactly `>---` (trailing spaces don't matter) can't be stored, because it would break the format. See [Skipped files](#skipped-files) for what happens then.

## Ignoring files

Put the ignore part **after** your sources. Everything after the first ignore keyword belongs to the ignore list.

| Keyword | Meaning |
|---|---|
| `*ignore <names...>` | Skip these names or paths |
| `*ignore-all` or `*ignorex` | Use the root `.gitignore` and `.ftxtignore` |
| `*ignore-i` | Use only the root `.gitignore` |
| `*ignore-f` | Use only the root `.ftxtignore` |

Keywords are case-insensitive and can be mixed. You can also add names after any of them.

```
writo out . *ignore .github .vscode keys
writo out . *ignorex
writo out . *ignorex dist coverage
writo out . *ignore-f
write src *ignore-i tests
```

Why the `*`? It is reserved on purpose, so it can never clash with a real folder called `ignore`.

### Manual names

`*ignore` takes any mix of files and folders. You don't have to say which is which.

* A plain name like `keys` matches any file or folder with that name, at any depth.
* An entry with a `/` like `docs/private` is a path from the root. It skips that path and everything under it.
* Ignored folders are never entered, so skipping `node_modules` or `.git` is fast.

`*ignore` alone, with no names, is an error.

### .gitignore and .ftxtignore

With `*ignore-all`, ftxt reads `.gitignore` and `.ftxtignore` from the root and uses their rules. The syntax is the regular gitignore one:

* `#` comments and blank lines
* `*`, `?`, `[abc]`, and `**` (`**/cache`, `docs/**/*.tmp`, `logs/**`)
* a leading `/` anchors a rule to the root (`/build`)
* a trailing `/` matches folders only (`dist/`)
* `!` re-includes something an earlier rule ignored
* `\#` and `\!` for names that really start with those characters
* last matching rule wins, and a file inside an ignored folder stays ignored

The matcher is built in, not a library. It was checked against real `git ls-files --others --exclude-standard` on a mixed test project and gave the identical file list.

**`.ftxtignore`** is yours. It works exactly like `.gitignore`, but only ftxt reads it. Use it for things git should track but you don't want in the text file (lock files, big generated data, test fixtures):

```
# .ftxtignore
package-lock.json
*.min.js
fixtures/
.ftxtignore
```

How the two files combine:

* The rules are merged, `.gitignore` first and `.ftxtignore` after. Since the last match wins, `.ftxtignore` can undo a `.gitignore` rule with `!`.
* A rule that appears in both files is only kept once. This never changes the result.
* The files can list themselves. If `.gitignore` contains `.gitignore`, that file is skipped. Same for `.ftxtignore`. If they don't list themselves, they are packed like any other text file.
* In git modes (`*ignore-all`, `*ignore-i`), the `.git` folder is skipped automatically, because git never tracks it either.

When a file is missing:

* `*ignore-i` without a `.gitignore` fails with `.gitignore not found in root`. Same for `*ignore-f` and `.ftxtignore`.
* `*ignore-all` is happy with either file. It only fails if neither exists (`no .gitignore or .ftxtignore found in root`).

Failing loudly is on purpose. Otherwise a typo or a missing file would silently pack your whole `venv`.

Only the root files are read. `.gitignore` files in subfolders are not.

## Skipped files

Some files can't or shouldn't go into the text file. ftxt skips them and keeps going, as long as you are writing a batch.

**Binary and unreadable files.** ftxt looks inside each file instead of trusting the extension, the same trick git uses:

1. If the first 8 KB contain a null byte, it is binary.
2. If those bytes aren't valid UTF-8, it is not readable text.

A file that fails to decode later, or can't be opened at all, is skipped too. You get a single summary line at the end:

```
skipped 39 binary/unreadable file(s)
```

So you don't need to ignore images, PDFs, compiled files and so on by hand.

**Files with the reserved line.** A file containing a `>---` line is skipped, with the reason:

```
skipped AHELPER/out.txt for containing reserved line '>---'
```

This one shows up a lot when you have other out files in the project, since every out file is full of `>---`. Ignore that folder if the message bothers you.

### Batch vs single file

* **Single file:** exactly one source, and it is a file (`write src/app.py`). Problems are errors, you get `fail: ...`.
* **Batch:** a folder, or more than one source (`writo out .`, `write a.py b.py`). Problem files are skipped and the rest is written.

If every file ends up skipped, you get `fail: nothing to write`.

## Safety rules

ftxt is built around a few hard rules:

* **It never deletes a folder.** There is no command for that. `rmf` and `empty` refuse folders (`refused: target is a directory`).
* **One file at a time.** `rmf` removes one `.txt` file. There is no wildcard and no recursive delete.
* **`empty` is picky.** It needs an explicit target (no guessing from the selection), won't create missing files, and refuses `.txt` files that aren't valid ftxt record files. Your `notes.txt` is safe from a typo.
* **Targets are only `.txt`.** Nothing else can be written, emptied or removed.
* **Folders stay inside the root.**

One honest caveat: `rmf` deletes any single `.txt` file you point it at, not only ftxt out files. Check the name.

## Messages

| Message | Meaning |
|---|---|
| `roger` | Done |
| `fail: <reason>` | Something is wrong, nothing was changed |
| `skipped <path> for ...` | One file in a batch was left out |
| `skipped N binary/unreadable file(s)` | Summary of left out binaries |

Typing an unknown command gives `fail: unknown command: <name>`.

## Recipes

Pack the whole project, respecting your ignore files:

```
writo out . *ignorex
```

Pack the whole project, ignoring a few names by hand:

```
writo out . *ignore .git venv node_modules dist .env
```

Keep snapshots in their own folder:

```
mkdirc snapshots
writo snapshots/v1 . *ignorex
```

Refresh the same snapshot later:

```
empty snapshots/v1
writo snapshots/v1 . *ignorex
```

Or skip the `empty`. Writing again updates records in place, though files you deleted from the project would stay in the old snapshot, so `empty` first gives you a clean one.

Pack just a few things:

```
writo out src/main.py docs README.md
```

## Notes

* ftxt is interactive only. Start `ftxt` and type commands at the prompt.
* Files are read as UTF-8.
* Paths in records always use `/`, even on Windows. On Windows, ignore name matching is case-insensitive.