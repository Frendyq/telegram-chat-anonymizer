#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа для TelegramAnonymizer.exe (и для запуска без параметров).

  * запуск двойным кликом — откроется окно выбора файла result.json;
  * перетаскивание result.json (или всей папки ChatExport_…) на .exe — сразу обработка;
  * после анонимизации автоматически запускается проверка на утечки.

Остальные параметры можно передать после пути, как у anonymize_tg.py:
  TelegramAnonymizer.exe result.json --no-dates
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import anonymize_tg
import check_anon


def pick_file() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return input("Укажите путь к result.json и нажмите Enter: ").strip().strip('"') or None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="Выберите result.json из экспорта Telegram",
        filetypes=[("Экспорт Telegram (JSON)", "*.json"), ("Все файлы", "*.*")],
    )
    root.destroy()
    return path or None


def run_module(main, argv: list[str]) -> int:
    old = sys.argv
    sys.argv = argv
    try:
        main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.argv = old


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    print("Telegram Chat Anonymizer — https://github.com/Frendyq/telegram-chat-anonymizer\n")

    args = sys.argv[1:]
    if not args:
        picked = pick_file()
        if not picked:
            print("Файл не выбран.")
            return 1
        args = [picked]

    src = Path(args[0])
    if src.is_dir():  # перетащили всю папку ChatExport_…
        src = src / "result.json"
    if not src.exists():
        print(f"Не найден файл: {src}")
        return 1
    extra = args[1:]

    out_json = src.with_name(src.stem + "_anon.json")
    for flag in ("-o", "--output"):
        if flag in extra and extra.index(flag) + 1 < len(extra):
            out_json = Path(extra[extra.index(flag) + 1])
    base = str(src.with_name(src.stem))
    anon_argv = ["anonymize_tg", str(src)]
    if "--txt" not in extra:
        anon_argv += ["--txt", base + "_anon.txt"]
    if "--suggest" not in extra:
        anon_argv += ["--suggest", base + "_suggest.txt"]
    anon_argv += extra

    code = run_module(anonymize_tg.main, anon_argv)
    if code != 0:
        return code

    print("\n===== Проверка результата =====")
    run_module(check_anon.main, ["check_anon", str(out_json)])

    print(f"\nГотово. Рядом с {src.name} появились:")
    print(f"  {out_json.name:<28} — обезличенный чат")
    print(f"  {Path(base + '_anon.txt').name:<28} — то же простым текстом")
    print(f"  {Path(base + '_suggest.txt').name:<28} — слова, похожие на пропущенные имена")
    print(f"\nСвои списки имён и слов положите рядом с программой: {anonymize_tg.app_dir()}")
    print("  names.txt — имена, hide.txt — места и названия, keep.txt — слова-исключения")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        traceback.print_exc()
        rc = 1
    if getattr(sys, "frozen", False) or len(sys.argv) <= 1:
        try:
            input("\nНажмите Enter, чтобы закрыть окно…")
        except EOFError:
            pass
    sys.exit(rc)
