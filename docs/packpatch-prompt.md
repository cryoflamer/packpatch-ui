# PackPatch prompt for ChatGPT

Use this prompt when sending a `chatgpt-pack-*.tar.gz` archive to ChatGPT and asking it to produce a patch.

The goal is to force a deterministic workflow:

```text
archive repo -> real edits -> git diff -> patch
```

## Full prompt

```text
You are working in PackPatch mode.

Input:
- I provide a `chatgpt-pack-*.tar.gz` archive.
- The archive contains a disposable git repository.
- This archive is the only source of truth.

Task:
- Modify the repository according to my request.
- Produce a patch generated from the real repository state.

Rules:
1. Use only files from the provided `chatgpt-pack-*` archive.
2. Do not use old files, cached files, or prior conversation context as source code.
3. Do not reconstruct files manually.
4. Work inside the unpacked disposable git repository.
5. Make changes to real files in that repository.
6. Produce the patch only via `git diff`.
7. The patch must use real paths from the repository.
8. The patch must be valid for `git apply`.
9. Validate with `git apply --check` before returning it.
10. Syntax-check changed files when applicable.
11. Do not include explanations inside the patch.
12. Do not change unrelated formatting or whitespace.
13. If the task is unclear or the archive structure is ambiguous, say so instead of guessing.

Output:
- Provide exactly one `.patch` file.
- Do not provide sidecar files such as `patch.base.sha256` or `patch.meta.json`.
- Write the commit message and a short change summary in chat.

Commit message format:
- One line.
- English.
- Passive voice.

Important:
- Do not output a synthetic or approximate patch.
- Do not paste a hand-written diff in chat unless file generation fails.
- The patch must come from `git diff`.
```

## Short prompt

Use this when the full rule is already established in the conversation:

```text
Use PackPatch mode. Use only the provided `chatgpt-pack-*` archive as source of truth. Work inside the unpacked disposable git repo. Produce exactly one valid `.patch` file only via `git diff`; validate with `git apply --check`; syntax-check changed files when applicable. Write the commit message and a short change summary in chat.
```

## Continuation mode

For quick iterations, PackPatch can be continued without creating a new archive every time.

Continuation rule:

```text
If I ask for another PackPatch and do not provide a new `chatgpt-pack-*` archive, continue from the last used pack by applying the previously generated PackPatch files in order, then produce the next patch from that updated repository state.
```

This is useful for small follow-up changes such as:

- adjust wording;
- add one button;
- fix a small bug;
- update docs;
- refine UI behavior.

Do not use continuation mode when:

- the previous patch failed to apply;
- conflicts were resolved manually outside ChatGPT;
- the local repository changed in ways ChatGPT cannot see;
- the base pack is unclear;
- several pack archives could apply and the latest one is ambiguous.

In those cases, create and upload a fresh pack.

## Expected assistant behavior

A correct PackPatch assistant should:

1. unpack the archive;
2. inspect the real repository paths;
3. edit files in place;
4. run `git diff`;
5. verify the patch;
6. return exactly one patch file;
7. summarize what changed;
8. provide the commit message in chat.

## Example request

```text
Use PackPatch mode. Add a filter field above the repository file tree.
```

Expected result:

- a downloadable `.patch` file;
- chat message such as:

```text
Commit message: Add file tree filter

What to verify:
- Filter files... field appears above the tree.
- Filtering by `main_window.py`, `tools/`, or `docs/` works.
- Selected files are not lost while filtering.
```

## Notes

PackPatch is designed to prevent common LLM patch failures:

- wrong paths;
- stale files;
- manually fabricated diffs;
- hidden context mixing;
- non-applicable patches.

The archive is the source of truth. The patch must be a real git diff from that archive.
