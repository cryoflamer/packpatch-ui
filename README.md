# PackPatch UI

Desktop UI for a deterministic patch workflow based on disposable git repositories.

PackPatch UI helps you select project files, create minimal repository packs, send them to ChatGPT, apply generated patches, and optionally commit the result without manually juggling patch files and shell commands.

## Why this exists

Manual patch workflows are easy to break:

- the wrong version of a file gets used;
- patches are produced against guessed paths;
- patch files fail to apply cleanly;
- conflict fallback is hard to repeat consistently;
- local state such as selected files, patch directories, and window layout gets lost.

PackPatch UI turns that into a repeatable loop:

```text
repo -> pack -> ChatGPT -> patch -> apply -> commit
```

The core rule is simple: ChatGPT works from a disposable git repository archive and returns either a PackPatch `git diff` file or a Compatсh `git format-patch` file.

For the prompt that should be given to ChatGPT, see [docs/packpatch-prompt.md](docs/packpatch-prompt.md).

## Features

### Pack creation

Supported pack modes:

- `slice` — selected files only;
- `changed` — modified and staged tracked files, with unversioned files included only when enabled;
- `full` — tracked project files;
- `full + untracked` — tracked files plus untracked non-ignored files.

`Git history depth` in Settings controls how many real source commits are preserved in every pack mode. The default is `1`; `0` uses a synthetic disposable base with no source history.

Packs are created with `tools/pack-for-chatgpt.sh` and stored in `chatgpt-packs/`.

### File selection

- repository file tree with checkboxes;
- directory selection with full and partial states;
- `Select changed` action;
- file filter/search;
- selected files are saved in the current session.

### Patch workflow

- list latest pack archives;
- list patch files from the configured patch directory;
- check latest PackPatch files with `git apply --check`;
- apply patch files with selectable PackPatch/Compatсh strategy;
- fallback support between `git am` and `git apply`;
- patch preview panel;
- structured log output with `Status`, `Details`, and `Debug` verbosity filters; warnings and errors stay visible at every level.

### Commit workflow

If `Apply commit message` is empty, a PackPatch is only applied to the index and working tree.

If `Apply commit message` is not empty, PackPatch apply creates a local commit using that message. Compatсh patches already carry their own commit message and are applied with `git am`.

The UI also includes:

- recent git commits panel;
- `Undo last commit`, implemented as `git reset --mixed HEAD~1`.

### Sessions

Sessions are saved locally and autosaved while the UI is used.

A session remembers:

- repository path;
- patch directory;
- task name;
- commit message;
- selected files;
- collapsed/expanded UI sections;
- window geometry;
- per-session log verbosity.

Session data is stored under the user config directory, for example:

```text
~/.config/packpatch-ui/sessions.json
```

## Installation

Create a virtual environment and install the package in editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Install PySide6 if it is not already installed by your environment:

```bash
pip install PySide6
```

## Run

From the repository root:

```bash
python -m packpatch_ui
```

## Basic workflow

### 1. Select a repository

Choose a git repository in the UI. The app shows git root, branch, and dirty/clean status.

### 2. Select files

Use the file tree, filter, directory checkboxes, or `Select changed`.

### 3. Create a pack

Choose `Pack mode`, set or accept the pack name, configure `Git history depth` in Settings if needed, then click `Create pack`.

The archive appears in:

```text
chatgpt-packs/
```

### 4. Send pack to ChatGPT

Upload the pack and use the PackPatch prompt:

[docs/packpatch-prompt.md](docs/packpatch-prompt.md)

### 5. Download the returned patch

Put the patch file into your configured patch directory, for example:

```text
/mnt/c/Users/Lenovo/Downloads
```

### 6. Check and apply

Use:

- `Check latest patch` to dry-run the patch;
- `Patch preview` to inspect the diff;
- `Apply latest patch` to apply it.

If a commit message is present, the patch is applied and committed.

## Safety model

PackPatch UI is intentionally conservative:

- packs are disposable git repositories;
- patches are expected to be real `git diff` output;
- `git apply --check` is available before PackPatch apply;
- selectable apply strategies support PackPatch and Compatсh files;
- undoing the last commit keeps changes in the working tree.

The UI does not make ChatGPT the source of truth. The pack archive and your local git repository remain the source of truth.

## Related documents

- [PackPatch prompt for ChatGPT](docs/packpatch-prompt.md)
- [Pack creation utility](docs/pack-for-chatgpt-docs.md)
- [Apply latest patch utility](docs/apply-latest-patch.md)

## License

TBD
