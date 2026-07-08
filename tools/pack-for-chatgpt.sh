#!/usr/bin/env bash
set -euo pipefail

# pack-for-chatgpt.sh
#
# Creates disposable git repositories for ChatGPT patch/review workflows.
#
# Modes:
#   full    <task-name> [--history-depth N] [--include-untracked]
#   slice   <task-name> [--history-depth N] [--include-untracked] <file-or-dir>...
#   changed <task-name> [--history-depth N] [--include-untracked]
#   history <task-name> [--depth N | --full-history]
#
# Examples:
#   ./pack-for-chatgpt.sh full overview --history-depth 1
#   ./pack-for-chatgpt.sh slice fix-phase-ui src/wedge/ui.py etc/config.yaml
#   ./pack-for-chatgpt.sh slice docs-task docs/ src/wedge/
#   ./pack-for-chatgpt.sh changed review-local-edits
#   ./pack-for-chatgpt.sh history investigate-regression --depth 100
#   ./pack-for-chatgpt.sh history investigate-regression --full-history
#
# Output:
#   chatgpt-packs/chatgpt-pack-<mode>-<task>-<timestamp>.tar.gz
#
# Archive structure:
#   chatgpt-pack/
#     .git/
#     <project files...>
#     CHATGPT_PACK_USAGE.md
#     patch.base.sha256
#     patch.meta.json

PACKPATCH_TMP_PARENT=""

cleanup_tmp_parent() {
    if [[ -n "${PACKPATCH_TMP_PARENT:-}" && -d "$PACKPATCH_TMP_PARENT" ]]; then
        rm -rf -- "$PACKPATCH_TMP_PARENT"
    fi
}

usage() {
    cat <<'EOF'
Usage:
  pack-for-chatgpt.sh full    <task-name> [--history-depth N] [--include-untracked] [--include-sensitive]
  pack-for-chatgpt.sh slice   <task-name> [--history-depth N] [--include-untracked] [--include-sensitive] <file-or-dir>...
  pack-for-chatgpt.sh changed <task-name> [--history-depth N] [--include-untracked] [--include-sensitive]
  pack-for-chatgpt.sh history <task-name> [--depth N | --full-history]

Modes:
  full
    Creates a disposable repo with all tracked files.
    --history-depth N preserves N real source commits; 0 uses a synthetic base.
    With --include-untracked, also includes untracked non-ignored files.
    With --include-sensitive, also includes tracked keys/certificates that are excluded by default.

  slice
    Creates a disposable repo with only selected files/directories in the working tree.
    --history-depth N preserves N real source commits; 0 uses a synthetic base.
    Paths are preserved relative to the project root.
    By default only tracked files are eligible. With --include-untracked,
    selected untracked non-ignored files are eligible too. Raw find is not used,
    so caches/build outputs are not accidentally packed.

  changed
    Creates a disposable repo with changed tracked files in the working tree.
    --history-depth N preserves N real source commits; 0 uses a synthetic base.
    With --include-untracked, also includes untracked non-ignored files.

  history
    Creates a shallow clone with real git history and working tree diff.
    Use only when git log/blame/history is needed.
    Default depth: 50. Use --full-history to include all reachable history.

Environment:
  CHATGPT_PACK_OUT_DIR
    Output directory. Default: chatgpt-packs

Examples:
  ./pack-for-chatgpt.sh full overview
  ./pack-for-chatgpt.sh full overview --include-untracked
  ./pack-for-chatgpt.sh full overview --include-sensitive
  ./pack-for-chatgpt.sh slice fix-ui src/app.py docs/SPEC.md
  ./pack-for-chatgpt.sh slice docs-review docs/
  ./pack-for-chatgpt.sh slice docs-review --include-untracked docs/
  ./pack-for-chatgpt.sh changed review-edits
  ./pack-for-chatgpt.sh changed review-edits --include-untracked
  ./pack-for-chatgpt.sh history investigate --depth 50
EOF
}

die() {
    echo "error: $*" >&2
    exit 1
}

warn() {
    echo "warning: $*" >&2
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

json_escape() {
    python3 -c 'import json, sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$1"
}

sanitize_task_name() {
    local raw="$1"
    local safe
    safe="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9._-]+/-/g; s/^-+//; s/-+$//')"
    [[ -n "$safe" ]] || safe="task"
    printf '%.80s' "$safe"
}

repo_root() {
    git rev-parse --show-toplevel 2>/dev/null || die "not inside a git repository"
}

is_safe_relative_path() {
    local p="$1"
    [[ -n "$p" ]] || return 1
    [[ "$p" != /* ]] || return 1
    [[ "$p" != "." ]] || return 1
    [[ "$p" != ".." ]] || return 1
    [[ "$p" != ../* ]] || return 1
    [[ "$p" != */../* ]] || return 1
    [[ "$p" != */.. ]] || return 1
    return 0
}

is_safe_env_template_path() {
    local p="$1"

    case "$p" in
        .env.example|*/.env.example) return 0 ;;
        .env.sample|*/.env.sample) return 0 ;;
        .env.template|*/.env.template) return 0 ;;
        .env.dist|*/.env.dist) return 0 ;;
    esac

    return 1
}

is_sensitive_path() {
    local p="$1"

    if is_safe_env_template_path "$p"; then
        return 1
    fi

    case "$p" in
        .env|.env.*|*/.env|*/.env.*) return 0 ;;
        id_rsa|id_rsa.pub|id_ed25519|id_ed25519.pub) return 0 ;;
        */id_rsa|*/id_rsa.pub|*/id_ed25519|*/id_ed25519.pub) return 0 ;;
        *.pem|*.key|*.p12|*.pfx|*.crt|*.cer) return 0 ;;
    esac

    return 1
}

should_exclude_path() {
    local p="$1"

    case "$p" in
        .git|.git/*) return 0 ;;

        chatgpt-packs|chatgpt-packs/*|*/chatgpt-packs|*/chatgpt-packs/*) return 0 ;;
        *.tar|*.tar.gz|*.tgz|*.zip|*.7z|*.rar) return 0 ;;

        .venv|.venv/*|venv|venv/*|env|env/*) return 0 ;;
        node_modules|node_modules/*|*/node_modules|*/node_modules/*) return 0 ;;
        __pycache__|*/__pycache__|*/__pycache__/*) return 0 ;;
        .mypy_cache|.mypy_cache/*|*/.mypy_cache|*/.mypy_cache/*) return 0 ;;
        .pytest_cache|.pytest_cache/*|*/.pytest_cache|*/.pytest_cache/*) return 0 ;;
        .ruff_cache|.ruff_cache/*|*/.ruff_cache|*/.ruff_cache/*) return 0 ;;
        .idea|.idea/*|*/.idea|*/.idea/*) return 0 ;;
        .vscode|.vscode/*|*/.vscode|*/.vscode/*) return 0 ;;
        build|build/*|*/build|*/build/*) return 0 ;;
        dist|dist/*|*/dist|*/dist/*) return 0 ;;
        target|target/*|*/target|*/target/*) return 0 ;;
        .DS_Store|*/.DS_Store) return 0 ;;

        *.mp4|*.mov|*.avi|*.mkv|*.webm) return 0 ;;
        *.pt|*.pth|*.onnx|*.engine) return 0 ;;
    esac

    return 1
}

should_exclude_file() {
    local root="$1"
    local p="$2"
    local include_sensitive="$3"

    if is_sensitive_path "$p"; then
        if [[ "$include_sensitive" == "1" ]] && git -C "$root" ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then
            return 1
        fi
        return 0
    fi

    should_exclude_path "$p"
}

copy_file_preserve_path() {
    local root="$1"
    local dst="$2"
    local rel="$3"

    is_safe_relative_path "$rel" || die "unsafe path: $rel"
    [[ -f "$root/$rel" ]] || die "not a file: $rel"

    mkdir -p "$dst/$(dirname "$rel")"
    cp -p "$root/$rel" "$dst/$rel"
}

copy_paths_from_nul_stream() {
    local root="$1"
    local dst="$2"
    local include_sensitive="${3:-0}"
    local count=0

    while IFS= read -r -d '' rel; do
        [[ -n "$rel" ]] || continue
        is_safe_relative_path "$rel" || die "unsafe path from git: $rel"
        if should_exclude_file "$root" "$rel" "$include_sensitive"; then
            continue
        fi
        if [[ -f "$root/$rel" ]]; then
            copy_file_preserve_path "$root" "$dst" "$rel"
            count=$((count + 1))
        fi
    done

    printf '%s\n' "$count"
}

collect_tracked_files() {
    git ls-files -z
}

collect_untracked_files() {
    git ls-files --others --exclude-standard -z
}

collect_changed_files() {
    local include_untracked="${1:-0}"
    {
        git diff --name-only -z HEAD
        git diff --name-only -z --cached HEAD
        if [[ "$include_untracked" == "1" ]]; then
            git ls-files --others --exclude-standard -z
        fi
    } | awk -v RS='\0' -v ORS='\0' 'NF && !seen[$0]++ { print }'
}

collect_git_known_files() {
    local include_untracked="${1:-0}"
    {
        git ls-files -z
        if [[ "$include_untracked" == "1" ]]; then
            git ls-files --others --exclude-standard -z
        fi
    } | awk -v RS='\0' -v ORS='\0' 'NF && !seen[$0]++ { print }'
}

path_is_inside_slice() {
    local file="$1"
    local slice="$2"

    [[ "$file" == "$slice" ]] && return 0
    [[ "$file" == "$slice/"* ]] && return 0
    return 1
}

copy_slice_path() {
    local root="$1"
    local dst="$2"
    local rel="$3"
    local tmp_list="$4"
    local include_sensitive="${5:-0}"
    local copied=0
    local file

    rel="${rel%/}"

    is_safe_relative_path "$rel" || die "unsafe slice path: $rel"
    [[ -e "$root/$rel" ]] || die "path does not exist: $rel"

    if [[ -f "$root/$rel" ]]; then
        if ! should_exclude_file "$root" "$rel" "$include_sensitive"; then
            copy_file_preserve_path "$root" "$dst" "$rel"
            copied=$((copied + 1))
        fi
    elif [[ -d "$root/$rel" ]]; then
        while IFS= read -r -d '' file; do
            [[ -n "$file" ]] || continue
            if path_is_inside_slice "$file" "$rel" && ! should_exclude_file "$root" "$file" "$include_sensitive"; then
                copy_file_preserve_path "$root" "$dst" "$file"
                copied=$((copied + 1))
            fi
        done < "$tmp_list"
    else
        die "unsupported path type: $rel"
    fi

    printf '%s\n' "$copied"
}

write_sha256_manifest() {
    local pack_dir="$1"

    (
        cd "$pack_dir"
        find . \
            -path './.git' -prune -o \
            -path './.git/*' -prune -o \
            -type f \
            ! -name 'patch.base.sha256' \
            ! -name 'patch.meta.json' \
            -print0 \
        | sort -z \
        | xargs -0 sha256sum
    ) > "$pack_dir/patch.base.sha256"
}

write_usage_file() {
    local pack_dir="$1"

    cat > "$pack_dir/CHATGPT_PACK_USAGE.md" <<'EOF'
# ChatGPT disposable repository pack

This archive contains a disposable git repository prepared for review or deterministic patch generation.

The user may request one of two workflows. Follow the requested mode.

## Shared rules

1. Treat this archive as the only source of truth.
2. Work inside `chatgpt-pack/` and edit real files only.
3. Do not reconstruct files manually or mix source from another archive.
4. Inspect `git status` and the repository history before editing.
5. Return exactly one `.patch` file and no metadata/checksum sidecars.
6. Run relevant syntax or project checks when applicable.

## PackPatch mode

When the user explicitly requests PackPatch mode:

1. Make the requested edits.
2. Generate the deliverable only from `git diff`.
3. Validate it against a clean copy of this base with `git apply --check`.
4. Return exactly one `.patch` file.
5. Provide a one-line English passive-voice commit message and a short change summary in chat.

Do not package PackPatch with `git format-patch`.

## Compatсh mode

When the user explicitly requests Compatсh mode:

1. Make the requested edits.
2. Stage intended changes with `git add -A`.
3. Create one real commit with a one-line English passive-voice commit message.
4. Export exactly that commit with:

   `git format-patch -1 --stdout > <patch-name>.patch`

5. Validate the patch in a clean copy of this base with:

   `git am --3way <patch-name>.patch`

6. Verify that the `.patch` file exists and is non-empty before linking it.
7. Return exactly one `.patch` file and summarize the change and validation in chat.

Do not use `git diff` as the Compatсh deliverable.

## User command aliases

The current user may use these Ukrainian shorthand commands:

- `роби пакпатч` -> request PackPatch mode;
- `роби компатч` -> request Compatсh mode;
- `роби ще` -> continue the active workflow;
- `роби ще компатч` -> continue Compatсh mode.

Treat them as aliases. Equivalent explicit requests in other languages have the same meaning.

## Pack metadata

- `patch.base.sha256` contains SHA256 checksums for files included in this pack.
- `patch.meta.json` describes pack mode, source branch/head, history depth, and included files.
- Preserved source commits in `.git` are authoritative up to the recorded shallow depth; working tree files reflect the selected pack mode and current source working-tree state.
EOF
}

write_meta_json() {
    local pack_dir="$1"
    local mode="$2"
    local task_name="$3"
    local source_root="$4"
    local file_count="$5"
    local history_depth="${6:-}"

    local head_sha
    head_sha="$(git -C "$source_root" rev-parse HEAD 2>/dev/null || true)"

    local branch
    branch="$(git -C "$source_root" branch --show-current 2>/dev/null || true)"

    local timestamp
    timestamp="$(date -Iseconds)"

    local files_json
    files_json="$(
        cd "$pack_dir"
        find . \
            -path './.git' -prune -o \
            -path './.git/*' -prune -o \
            -type f \
            ! -name 'patch.base.sha256' \
            ! -name 'patch.meta.json' \
            -printf '%P\n' \
        | sort \
        | python3 -c 'import json,sys; print(json.dumps([line.rstrip("\n") for line in sys.stdin if line.strip()], ensure_ascii=False, indent=2))'
    )"

    python3 - \
        "$pack_dir/patch.meta.json" \
        "$mode" \
        "$task_name" \
        "$timestamp" \
        "$history_depth" \
        "$(basename "$source_root")" \
        "$branch" \
        "$head_sha" \
        "$file_count" \
        "$files_json" <<'PYMETA'
import json
import sys

(
    output_path,
    mode,
    task_name,
    timestamp,
    history_depth,
    root_basename,
    branch,
    head_sha,
    file_count,
    files_json,
) = sys.argv[1:]

meta = {
    "pack_format": "chatgpt-disposable-repo-v2",
    "mode": mode,
    "task": task_name,
    "created_at": timestamp,
    "history_depth": history_depth if history_depth else None,
    "source": {
        "root_basename": root_basename,
        "branch": branch,
        "head": head_sha,
    },
    "file_count": int(file_count),
    "files": json.loads(files_json),
}

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
    f.write("\n")
PYMETA
}

init_disposable_repo() {
    local pack_dir="$1"

    git -C "$pack_dir" init -q
    git -C "$pack_dir" config user.name "ChatGPT Pack Bot"
    git -C "$pack_dir" config user.email "chatgpt-pack@example.invalid"
    git -C "$pack_dir" add .
    git -C "$pack_dir" commit -q -m "base"
}

copy_git_identity() {
    local source_root="$1"
    local pack_dir="$2"
    local user_name
    local user_email

    user_name="$(git -C "$source_root" config user.name || true)"
    user_email="$(git -C "$source_root" config user.email || true)"

    if [[ -n "$user_name" ]]; then
        git -C "$pack_dir" config user.name "$user_name"
    fi
    if [[ -n "$user_email" ]]; then
        git -C "$pack_dir" config user.email "$user_email"
    fi
}

prepare_pack_repo() {
    local source_root="$1"
    local pack_dir="$2"
    local mode="$3"
    local history_depth="$4"
    local tmp_parent="$5"

    if [[ "$history_depth" == "0" ]]; then
        init_disposable_repo "$pack_dir"
        return
    fi

    local snapshot_dir="$tmp_parent/pack-snapshot"
    mv "$pack_dir" "$snapshot_dir"
    git clone -q --depth "$history_depth" "file://$source_root" "$pack_dir"

    if [[ "$mode" != "full" ]]; then
        git -C "$pack_dir" sparse-checkout init --no-cone
        (
            cd "$snapshot_dir"
            find . -type f \
                ! -name 'CHATGPT_PACK_USAGE.md' \
                ! -name 'patch.base.sha256' \
                ! -name 'patch.meta.json' \
                -printf '/%P\n' \
            | sort
        ) | git -C "$pack_dir" sparse-checkout set --no-cone --stdin
    fi

    find "$pack_dir" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf -- {} +
    cp -a "$snapshot_dir"/. "$pack_dir"/

    cat >> "$pack_dir/.git/info/exclude" <<'EOF'
/CHATGPT_PACK_USAGE.md
/patch.base.sha256
/patch.meta.json
EOF
    copy_git_identity "$source_root" "$pack_dir"
}

next_counter() {
    local out_dir="$1"
    local state_file="$out_dir/.chatgpt-pack-counter"
    local n=1

    mkdir -p "$out_dir"

    if [[ -f "$state_file" ]]; then
        n="$(cat "$state_file")"
        [[ "$n" =~ ^[0-9]+$ ]] || n=0
        n=$((n + 1))
    fi

    printf '%s\n' "$n" > "$state_file"
    printf '%03d' "$n"
}

make_archive_name() {
    local out_dir="$1"
    local mode="$2"
    local task="$3"

    local timestamp
    timestamp="$(date +%Y%m%d-%H%M)"

    local base="$out_dir/chatgpt-pack-${mode}-${task}-${timestamp}"
    local candidate="${base}.tar.gz"

    if [[ ! -e "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return
    fi

    local i=1
    while true; do
        candidate="${base} (${i}).tar.gz"
        if [[ ! -e "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return
        fi
        i=$((i + 1))
    done
}

create_clean_pack_dir() {
    local tmp_parent="$1"
    local pack_dir="$tmp_parent/chatgpt-pack"
    mkdir -p "$pack_dir"
    printf '%s\n' "$pack_dir"
}

archive_pack_dir() {
    local pack_dir="$1"
    local archive="$2"

    local parent
    parent="$(dirname "$pack_dir")"

    tar -C "$parent" -czf "$archive" "$(basename "$pack_dir")"
    printf '%s\n' "$archive"
}

ensure_clean_or_warn() {
    local root="$1"

    if ! git -C "$root" diff --quiet || ! git -C "$root" diff --cached --quiet; then
        warn "repository has uncommitted tracked changes; packed files reflect working tree state"
    fi
}

print_result() {
    local archive="$1"
    local mode="$2"

    echo
    echo "Created:"
    echo "  $archive"
    echo
    echo "Archive root:"
    echo "  chatgpt-pack/"
    echo
    if [[ "$mode" == "history" ]]; then
        echo "History mode warning:"
        echo "  This archive may contain private git history. Share it only intentionally."
        echo
    fi
    echo "Check:"
    echo "  tar tzf \"$archive\" | head"
}

pack_full() {
    local root="$1"
    local task="$2"
    local include_untracked="$3"
    local include_sensitive="$4"
    local history_depth="$5"
    local tmp_parent="$6"
    local out_dir="$7"

    local pack_dir
    pack_dir="$(create_clean_pack_dir "$tmp_parent")"

    local count=0
    local c

    c="$(collect_tracked_files | copy_paths_from_nul_stream "$root" "$pack_dir" "$include_sensitive")"
    count=$((count + c))

    if [[ "$include_untracked" == "1" ]]; then
        c="$(collect_untracked_files | copy_paths_from_nul_stream "$root" "$pack_dir" "0")"
        count=$((count + c))
    fi

    [[ "$count" -gt 0 ]] || die "no files copied"

    write_usage_file "$pack_dir"
    write_sha256_manifest "$pack_dir"
    write_meta_json "$pack_dir" "full" "$task" "$root" "$count" "$history_depth"
    prepare_pack_repo "$root" "$pack_dir" "full" "$history_depth" "$tmp_parent"

    local archive
    archive="$(make_archive_name "$out_dir" "full" "$task" "$pack_dir")"
    archive_pack_dir "$pack_dir" "$archive"
    print_result "$archive" "full"
}

pack_slice() {
    local root="$1"
    local task="$2"
    local include_sensitive="$3"
    local include_untracked="$4"
    local history_depth="$5"
    local tmp_parent="$6"
    local out_dir="$7"
    shift 7

    [[ "$#" -gt 0 ]] || die "slice mode requires at least one path"

    local pack_dir
    pack_dir="$(create_clean_pack_dir "$tmp_parent")"

    local tmp_list="$tmp_parent/git-known-files.nul"
    collect_git_known_files "$include_untracked" > "$tmp_list"

    local count=0
    local c
    local p

    for p in "$@"; do
        c="$(copy_slice_path "$root" "$pack_dir" "$p" "$tmp_list" "$include_sensitive")"
        count=$((count + c))
    done

    [[ "$count" -gt 0 ]] || die "no files copied"

    write_usage_file "$pack_dir"
    write_sha256_manifest "$pack_dir"
    write_meta_json "$pack_dir" "slice" "$task" "$root" "$count" "$history_depth"
    prepare_pack_repo "$root" "$pack_dir" "slice" "$history_depth" "$tmp_parent"

    local archive
    archive="$(make_archive_name "$out_dir" "slice" "$task" "$pack_dir")"
    archive_pack_dir "$pack_dir" "$archive"
    print_result "$archive" "slice"
}

pack_changed() {
    local root="$1"
    local task="$2"
    local include_sensitive="$3"
    local include_untracked="$4"
    local history_depth="$5"
    local tmp_parent="$6"
    local out_dir="$7"

    local pack_dir
    pack_dir="$(create_clean_pack_dir "$tmp_parent")"

    local count
    count="$(collect_changed_files "$include_untracked" | copy_paths_from_nul_stream "$root" "$pack_dir" "$include_sensitive")"

    [[ "$count" -gt 0 ]] || die "no changed files to pack"

    write_usage_file "$pack_dir"
    write_sha256_manifest "$pack_dir"
    write_meta_json "$pack_dir" "changed" "$task" "$root" "$count" "$history_depth"
    prepare_pack_repo "$root" "$pack_dir" "changed" "$history_depth" "$tmp_parent"

    local archive
    archive="$(make_archive_name "$out_dir" "changed" "$task" "$pack_dir")"
    archive_pack_dir "$pack_dir" "$archive"
    print_result "$archive" "changed"
}

pack_history() {
    local root="$1"
    local task="$2"
    local depth="$3"
    local tmp_parent="$4"
    local out_dir="$5"

    warn "history mode can include private commit messages, deleted code, old secrets, branches reachable from HEAD, and authorship data"
    warn "use full/slice/changed for normal patch work"

    local pack_dir="$tmp_parent/chatgpt-pack"

    if [[ "$depth" == "0" ]]; then
        git clone -q "file://$root" "$pack_dir"
    else
        git clone -q --depth "$depth" "file://$root" "$pack_dir"
    fi

    (
        cd "$root"
        git diff --binary HEAD > "$tmp_parent/working-tree.patch"
    )

    if [[ -s "$tmp_parent/working-tree.patch" ]]; then
        if ! git -C "$pack_dir" apply --index "$tmp_parent/working-tree.patch"; then
            warn "could not apply working tree diff to history pack"
            warn "packing committed history only"
        fi
    fi

    write_usage_file "$pack_dir"
    write_sha256_manifest "$pack_dir"
    write_meta_json "$pack_dir" "history" "$task" "$root" "$(git -C "$pack_dir" ls-files | wc -l | tr -d ' ')" "$depth"

    git -C "$pack_dir" add CHATGPT_PACK_USAGE.md patch.base.sha256 patch.meta.json
    git -C "$pack_dir" commit -q -m "Add ChatGPT pack metadata" || true

    local archive
    archive="$(make_archive_name "$out_dir" "history" "$task" "$pack_dir")"
    archive_pack_dir "$pack_dir" "$archive"
    print_result "$archive" "history"
}

main() {
    need_cmd git
    need_cmd tar
    need_cmd sha256sum
    need_cmd python3
    need_cmd find
    need_cmd awk
    need_cmd sed
    need_cmd date

    [[ "$#" -ge 1 ]] || { usage; exit 1; }

    local mode="$1"
    shift

    case "$mode" in
        -h|--help|help)
            usage
            exit 0
            ;;
    esac

    local root
    root="$(repo_root)"
    cd "$root"

    local task_raw="${1:-}"
    [[ -n "$task_raw" ]] || { usage; die "missing task name"; }
    shift

    local task
    task="$(sanitize_task_name "$task_raw")"

    PACKPATCH_TMP_PARENT="$(mktemp -d)"
    trap cleanup_tmp_parent EXIT

    local out_dir="${CHATGPT_PACK_OUT_DIR:-$root/chatgpt-packs}"
    mkdir -p "$out_dir"

    ensure_clean_or_warn "$root"

    case "$mode" in
        full)
            local include_untracked="0"
            local include_sensitive="0"
            local history_depth="0"
            while [[ "$#" -gt 0 ]]; do
                case "$1" in
                    --include-untracked) include_untracked="1" ;;
                    --include-sensitive) include_sensitive="1" ;;
                    --history-depth)
                        shift
                        [[ "${1:-}" =~ ^[0-9]+$ ]] || die "--history-depth requires a non-negative number"
                        history_depth="$1"
                        ;;
                    *) die "unknown full option: $1" ;;
                esac
                shift
            done
            pack_full "$root" "$task" "$include_untracked" "$include_sensitive" "$history_depth" "$PACKPATCH_TMP_PARENT" "$out_dir"
            ;;
        slice)
            local include_sensitive="0"
            local include_untracked="0"
            local history_depth="0"
            local slice_paths=()
            while [[ "$#" -gt 0 ]]; do
                case "$1" in
                    --include-sensitive) include_sensitive="1" ;;
                    --include-untracked) include_untracked="1" ;;
                    --history-depth)
                        shift
                        [[ "${1:-}" =~ ^[0-9]+$ ]] || die "--history-depth requires a non-negative number"
                        history_depth="$1"
                        ;;
                    *) slice_paths+=("$1") ;;
                esac
                shift
            done
            pack_slice "$root" "$task" "$include_sensitive" "$include_untracked" "$history_depth" "$PACKPATCH_TMP_PARENT" "$out_dir" "${slice_paths[@]}"
            ;;
        changed)
            local include_sensitive="0"
            local include_untracked="0"
            local history_depth="0"
            while [[ "$#" -gt 0 ]]; do
                case "$1" in
                    --include-sensitive) include_sensitive="1" ;;
                    --include-untracked) include_untracked="1" ;;
                    --history-depth)
                        shift
                        [[ "${1:-}" =~ ^[0-9]+$ ]] || die "--history-depth requires a non-negative number"
                        history_depth="$1"
                        ;;
                    *) die "unknown changed option: $1" ;;
                esac
                shift
            done
            pack_changed "$root" "$task" "$include_sensitive" "$include_untracked" "$history_depth" "$PACKPATCH_TMP_PARENT" "$out_dir"
            ;;
        history)
            local depth="50"
            while [[ "$#" -gt 0 ]]; do
                case "$1" in
                    --depth)
                        shift
                        [[ "${1:-}" =~ ^[0-9]+$ ]] || die "--depth requires a number; use 0 for full history"
                        depth="$1"
                        ;;
                    --full-history)
                        depth="0"
                        ;;
                    *)
                        die "unknown history option: $1"
                        ;;
                esac
                shift
            done
            pack_history "$root" "$task" "$depth" "$PACKPATCH_TMP_PARENT" "$out_dir"
            ;;
        *)
            usage
            die "unknown mode: $mode"
            ;;
    esac
}

main "$@"