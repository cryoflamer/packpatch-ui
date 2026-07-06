# pack-for-chatgpt.sh

Утиліта для створення disposable git-репозиторіїв для роботи з ChatGPT: рев'ю, аналізу, PackPatch і Compatсh.

## Опис

Утиліта створює архів із disposable git repository та потрібним working tree. Це зменшує зайвий контекст і дає ChatGPT реальну git-базу замість реконструйованих файлів.

## Pack modes

### full

Пакує всі tracked файли. `--include-untracked` додає untracked non-ignored files.

### slice

Залишає у working tree лише явно вибрані файли або директорії.

### changed

Пакує modified/staged tracked files. Untracked додаються лише з `--include-untracked`.

### history

Legacy CLI mode для окремого history-oriented pack. У PackPatch UI цей mode не показується: history depth тепер є окремим параметром і застосовується до звичайних pack modes.

## Git history depth

Для `full`, `slice` і `changed` опція `--history-depth N` визначає, скільки реальних source commits зберігається у `.git`.

- `N >= 1` зберігає реальний source `HEAD` і shallow history відповідної глибини.
- `N = 0` є lower-level CLI escape hatch і створює synthetic disposable base.
- PackPatch UI використовує minimum `1`, тому UI-created packs завжди зберігають реальний source `HEAD`.

Для `slice` і `changed` preserved history може містити committed versions файлів поза видимим working tree. Це очікувано: pack mode визначає working tree context, а history depth — git context.

## Приклади

```bash
./pack-for-chatgpt.sh full packpatch --history-depth 1
./pack-for-chatgpt.sh full vpn --include-untracked --history-depth 2
./pack-for-chatgpt.sh slice ias --history-depth 1 src/app.py docs/
./pack-for-chatgpt.sh changed ca --history-depth 1
./pack-for-chatgpt.sh history investigate --depth 50
```

## Вихід

Архів створюється у `chatgpt-packs/`.

Ім'я файлу:

```text
chatgpt-pack-<mode>-<pack-name>-<timestamp>.tar.gz
```

Якщо ім'я вже існує:

```text
chatgpt-pack-... (1).tar.gz
chatgpt-pack-... (2).tar.gz
```

## Структура архіву

```text
chatgpt-pack/
  .git/
  <project files selected by pack mode>
  patch.base.sha256
  patch.meta.json
  CHATGPT_PACK_USAGE.md
```

`CHATGPT_PACK_USAGE.md` містить короткі правила для обох assistant workflows:

- PackPatch: real `git diff`, validation via `git apply --check`;
- Compatсh: real commit, `git format-patch`, validation via `git am --3way`.

Повний canonical prompt знаходиться у `docs/packpatch-prompt.md`.

## Sensitive and unversioned files

- Unversioned files не включаються за замовчуванням; `--include-untracked` явно додає non-ignored untracked files.
- Sensitive key/certificate patterns виключаються за замовчуванням.
- `--include-sensitive` дозволяє включити tracked sensitive files. Untracked sensitive files лишаються виключеними.

Не передавай секрети без явної необхідності.

## Метадані

- `patch.base.sha256` — SHA256 manifest файлів pack working tree.
- `patch.meta.json` — mode, pack name/task metadata, source branch/head, history depth та included files.
- `.git` — preserved source history відповідно до history depth.

Disposable pack є source of truth для assistant operation. Preserved commits є authoritative в межах shallow depth, а working tree відображає mode-selected поточний стан source repo.
