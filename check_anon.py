#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка анонимизированного чата (result_anon.json) на остатки личных данных.

Проверяет НЕЗАВИСИМО от anonymize_tg.py, более грубыми правилами: всё, что
похоже на телефон, почту, карту, ссылку, пароль, адрес, документ или имя.
По умолчанию печатает ТОЛЬКО количество находок — без текста переписки.

Запуск:
  python check_anon.py "путь\\result_anon.json"
  python check_anon.py "путь\\result_anon.json" --show      # показать сами найденные слова
                                                           # (только их, без окружающего текста)
names.txt рядом со скриптом подхватывается автоматически.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anonymize_tg as A  # noqa: E402  (формы имён, словарь, транслит)

PLACEHOLDER = re.compile(r"\[(?:[А-ЯЁ]+(?:_\d+)?|Человек [^\]]+)\]")

# ---- правила проверки: (название, регулярка, должно ли быть 0) ----
CHECKS = [
    ("Почта", re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,}"), True),
    ("Телефон (+7, 8, 7xx…)", re.compile(
        r"(?<![\w])(?:\+?[78][\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}|\+\d[\d\s\-()]{9,16}\d)(?![\w])"), True),
    ("Номер карты (13–19 цифр)", re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)"), True),
    ("ИИН / 12 цифр подряд", re.compile(r"(?<!\d)\d{12}(?!\d)"), True),
    ("Ссылка", re.compile(r"(?i)\b(?:https?://|www\.)(?!localhost|127\.0\.0\.1)\S+"), True),
    ("@юзернейм", re.compile(r"(?<![\w@])@[A-Za-z][A-Za-z0-9_]{3,31}\b(?![/.\-]\w)"), True),
    ("t.me / instagram / vk", re.compile(r"(?i)\b(?:t\.me|telegram\.me|instagram\.com|vk\.com|wa\.me)/\S+"), True),
    ("Ключ=значение (пароль, токен…)", re.compile(
        r"(?i)(?<![A-Za-z])(?:password|passwd|pass|pwd|secret|token|api[_-]?key|пароль|токен|ключ)"
        r"[ \t]*[:=][ \t]*(?!\[|\.\.\.|…|<|your)[^\s\[]{3,}"), True),
    ("Паспорт / удостоверение + номер", re.compile(
        r"(?i)(?:паспорт\w*|удостоверени\w*|уд\.?\s?л\.?|ИИН|ID[\s-]?карт\w*)[^\d\n\[]{0,25}\d{6,}"), True),
    ("Код вида N12345678", re.compile(r"(?<![\w\-])[A-Z]{1,2}\d{7,8}(?![\w\-])"), True),
    ("Адрес (ул./мкр/дом/кв.)", re.compile(
        # сокращения (ул, мкр, ж/к) — с любым словом; полные слова («на улице …») — только
        # с названием с заглавной или с номером, иначе «на улице жара» — тоже «адрес»
        r"(?<![\w])(?:(?i:ул|мкрн?|пр-т|ж/к|жк)(?![\w/])\.?\s*(?!\[)[^\s,\[]{2,}"
        r"|(?i:улиц[аеуы]|улицей|микрорайон\w*|проспект\w*|переул\w*)\s+"
        r"(?:[А-ЯЁӘҒҚҢӨҰҮҺІ][\w\-]+|№?\s*\d+[а-яА-Яa-zA-Z]?(?![\w])))"
        r"(?:\s*,?\s*(?:д\.?|дом)?\s*\d+)?"), True),
    ("Координаты", re.compile(r"(?<![\d.])-?\d{1,2}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}"), True),
    ("Путь C:\\Users\\имя", re.compile(r"(?i)[a-z]:\\users\\(?!\[|public\\|default\\)[^\\\s]+"), True),
    # ниже — то, что может быть и нормальным (суммы, годы, техтермины): просто посмотрите
    ("7–11 цифр подряд (суммы? номера?)", re.compile(r"(?<![\d\[_])\d{7,11}(?![\d\]])"), False),
    ("Похоже на пароль/ключ (буквы+цифры)", re.compile(
        r"(?<![\w\[])(?=[A-Za-z0-9_!@#$%&*\-]{8,}(?![\w]))(?=[A-Za-z0-9_!@#$%&*\-]*[A-Za-z])"
        r"(?=(?:[A-Za-z0-9_!@#$%&*\-]*?\d){3})[A-Za-z0-9_!@#$%&*\-]+"), False),
    ("Домен (site.kz и т.п.)", re.compile(
        r"(?i)(?<![\w@.\-/])(?:[a-z0-9\-]+\.)+(?:kz|ru|com|net|org|io|me|app|dev|uz|kg|by|ua|co|ai)(?![\w\-])"), False),
]

PATRONYMIC = re.compile(r"(?<![\w])[А-ЯЁӘҒҚҢӨҰҮҺІ]\w+(?:ұлы|улы|қызы|кызы|ович|евич|овна|евна)\w{0,2}(?![\w])")


def collect_texts(data: dict):
    for m in data.get("messages", []):
        t = m.get("text", "")
        if isinstance(t, list):
            t = "".join(x if isinstance(x, str) else x.get("text", "") for x in t)
        yield m, t or ""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Проверка анонимизированного чата на остатки личных данных")
    ap.add_argument("input", help="result_anon.json")
    ap.add_argument("--names", help="names.txt (по умолчанию рядом со скриптом)")
    ap.add_argument("--show", action="store_true",
                    help="показать найденные слова (только их, без контекста), до 30 на категорию")
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    # имена из names.txt во всех формах
    names = A.NameIndex()
    names_file = A.default_file(args.names, "names.txt")
    for person in A.read_people(names_file):
        names.add_person(person)
    user_forms = {f for f, c in names.dict_forms.items() if c in names.user_canon}
    builtin = A.NameIndex()
    for n in A.load_builtin_names():
        builtin.add_dict_name(n)

    found: dict[str, Counter] = defaultdict(Counter)
    struct_problems: Counter = Counter()
    allowed_keys = {"id", "type", "date", "from", "from_id", "reply_to_message_id", "forwarded",
                    "forwarded_from", "media", "text", "text_entities"}
    labels = set(data.get("participants", []))

    for m, text in collect_texts(data):
        # структура: лишние поля, авторы
        for k in m:
            if k not in allowed_keys:
                struct_problems[f"лишнее поле «{k}»"] += 1
        if labels and m.get("from") not in labels:
            struct_problems["автор не «Человек А/Б»"] += 1
        fw = m.get("forwarded_from")
        if fw and fw not in labels and not re.fullmatch(r"\[ЧЕЛОВЕК_\d+\]", fw):
            struct_problems["источник пересылки не скрыт"] += 1

        clean = PLACEHOLDER.sub(" ", text)
        for title, rx, _ in CHECKS:
            for hit in rx.finditer(clean):
                v = hit.group(0)
                if title.startswith("Номер карты"):
                    d = re.sub(r"\D", "", v)
                    if not (13 <= len(d) <= 19 and A.luhn_ok(d)):
                        continue
                found[title][v] += 1
        for w in A.WORD_RE.finditer(clean):
            word = w.group(0)
            lw = A.norm(word)
            if lw in user_forms or names._by_prefix(lw, names.prefixes):
                canon = names.dict_forms.get(lw) or names._by_prefix(lw, names.prefixes)
                if word[0].islower() and canon in A.LOWER_AMBIGUOUS:
                    found["Омоним со строчной (мина, дана…)"][word] += 1
                else:
                    found["Имя из names.txt (должно быть 0)"][word] += 1
            elif lw in builtin.dict_forms and (word[0].isupper()
                                               or builtin.dict_forms[lw] not in A.LOWER_AMBIGUOUS):
                found["Имя из встроенного словаря"][word] += 1
        for hit in PATRONYMIC.finditer(clean):
            # то же правило, что в анонимизаторе: «Духовная», «Основная» — не отчества
            if A.PATRONYMIC_RE.search(hit.group(0)):
                found["ФИО с отчеством"][hit.group(0)] += 1

    must_zero = {t for t, _, z in CHECKS if z} | {"Имя из names.txt (должно быть 0)", "ФИО с отчеством"}
    order = [t for t, _, _ in CHECKS] + ["Имя из names.txt (должно быть 0)", "ФИО с отчеством",
                                          "Имя из встроенного словаря", "Омоним со строчной (мина, дана…)"]

    print(f"Сообщений проверено: {len(data.get('messages', []))}\n")
    print("ДОЛЖНО БЫТЬ 0:")
    for t in order:
        if t in must_zero:
            n = sum(found[t].values())
            print(f"  {'OK ' if n == 0 else '!! '} {t}: {n}")
    print("\nМОЖЕТ БЫТЬ НОРМОЙ (суммы, годы, техтермины, знаменитости) — посмотрите с --show:")
    for t in order:
        if t not in must_zero:
            print(f"  {'   '} {t}: {sum(found[t].values())} (разных: {len(found[t])})")
    print("\nСТРУКТУРА ФАЙЛА:")
    if struct_problems:
        for k, v in struct_problems.items():
            print(f"  !!  {k}: {v}")
    else:
        print("  OK  только «Человек А/Б», никаких id, юзернеймов и названий файлов")

    if args.show:
        print("\nНАЙДЕННЫЕ СЛОВА (без контекста):")
        for t in order:
            if found[t]:
                items = ", ".join(f"{v} ×{c}" for v, c in found[t].most_common(30))
                more = f" … и ещё {len(found[t]) - 30}" if len(found[t]) > 30 else ""
                print(f"\n  {t}:\n    {items}{more}")
    else:
        print("\nЧтобы увидеть сами найденные слова (без контекста), добавьте --show.")


if __name__ == "__main__":
    main()
