#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анонимизация экспорта чата Telegram Desktop (result.json).

Что делает:
  * оставляет сообщения двух участников (Человек А и Человек Б), включая
    пересланные ими; сообщения других людей и служебные события убирает;
  * заменяет авторов на «Человек А» / «Человек Б», удаляет id, юзернеймы,
    названия файлов, реакции; источник пересылки → «Человек А/Б» или [ЧЕЛОВЕК_n];
  * во ВСЕХ сообщениях (и в пересланных) вычищает: имена (в падежах,
    уменьшительные, латиницей), фамилии и отчества, @юзернеймы, почты,
    телефоны, номера карт, ИИН и длинные номера, ссылки и домены, пароли,
    токены, API-ключи, UUID и прочие секреты, адреса (ул./мкр/дом/кв.),
    координаты, номера паспортов, удостоверений, договоров, госномера машин;
  * одинаковые значения получают одинаковые метки: [ПОЧТА_1], [ИМЯ_2] …,
    поэтому переписку по-прежнему можно читать.

Запуск:
  python anonymize_tg.py result.json
  python anonymize_tg.py result.json -o anon.json --txt anon.txt --suggest suggest.txt

Файлы рядом со скриптом подхватываются автоматически:
  names.txt   имена для скрытия: строка = один человек, варианты через запятую
  hide.txt    любые слова/фразы для скрытия (компании, адреса, названия…)
  keep.txt    слова, которые НЕ надо считать именами
Другие параметры (подробно: python anonymize_tg.py -h):
  --suggest suggest.txt  список слов с заглавной буквы, оставшихся в тексте, —
                         удобно найти пропущенные имена и дописать их в names.txt
  --audit audit.txt   таблица «что → на что заменено» для проверки
                      (ВНИМАНИЕ: в ней исходные секреты, не передавайте её)

Если установлен пакет natasha (pip install natasha), имена людей на русском
дополнительно ищутся нейросетевой моделью — это ловит редкие имена,
которых нет во встроенном словаре.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# --------------------------------------------------------------------------
# Метки
# --------------------------------------------------------------------------


class Vault:
    """Выдаёт одинаковые метки одинаковым значениям и ведёт статистику."""

    def __init__(self) -> None:
        self.maps: dict[str, dict[str, str]] = defaultdict(dict)
        self.originals: dict[str, set[str]] = defaultdict(set)
        self.hits: Counter = Counter()

    @staticmethod
    def _key(cat: str, value: str) -> str:
        v = value.strip()
        if cat == "ТЕЛЕФОН":
            d = re.sub(r"\D", "", v)
            return d[-10:] if len(d) >= 10 else d
        if cat in ("КАРТА", "ИИН", "НОМЕР"):
            return re.sub(r"\D", "", v)
        if cat in ("ПОЧТА", "ДОМЕН", "НИК", "ИМЯ", "СКРЫТО"):
            return v.lower().replace("ё", "е")
        return v

    def tag(self, cat: str, value: str, key: str | None = None) -> str:
        k = key if key is not None else self._key(cat, value)
        m = self.maps[cat]
        if k not in m:
            m[k] = f"[{cat}_{len(m) + 1}]"
        self.hits[cat] += 1
        self.originals[m[k]].add(value)
        return m[k]


# --------------------------------------------------------------------------
# Транслитерация (для поиска «Dmitry» ↔ «Дмитрий»)
# --------------------------------------------------------------------------

_LAT2CYR_MULTI = [
    ("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"),
    ("ch", "ч"), ("sh", "ш"), ("ya", "я"), ("yu", "ю"), ("yo", "ё"),
    ("ye", "е"), ("ia", "ия"), ("iy", "ий"),
]
_LAT2CYR = dict(zip("abvgdezijklmnoprstufhcqwx",
                    "абвгдезийклмнопрстуфхкквкс"))
_LAT2CYR.update({"x": "кс"})
_CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ә": "a", "ғ": "g", "қ": "k", "ң": "n", "ө": "o", "ұ": "u", "ү": "u",
    "һ": "h", "і": "i",
}
_VOWELS_LAT = set("aeiouy")


def lat2cyr(word: str) -> str:
    w = word.lower()
    out, i = [], 0
    while i < len(w):
        for src, dst in _LAT2CYR_MULTI:
            if w.startswith(src, i):
                out.append(dst)
                i += len(src)
                break
        else:
            ch = w[i]
            if ch == "y":
                prev = w[i - 1] if i else ""
                out.append("й" if prev in _VOWELS_LAT else "ы")
            elif ch == "e" and i == 0:
                out.append("е")
            else:
                out.append(_LAT2CYR.get(ch, ch))
            i += 1
    return "".join(out)


def cyr2lat(word: str) -> str:
    return "".join(_CYR2LAT.get(ch, ch) for ch in word.lower())


def is_latin(word: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z'\-]+", word))


# --------------------------------------------------------------------------
# Имена
# --------------------------------------------------------------------------

def load_builtin_names() -> list[str]:
    """Встроенный словарь имён из builtin_names.txt рядом со скриптом."""
    path = Path(__file__).resolve().with_name("builtin_names.txt")
    if not path.exists():
        print(f"Внимание: не найден {path.name} — встроенный словарь имён не загружен.", file=sys.stderr)
        return []
    out: list[str] = []
    for ln in path.read_text(encoding="utf-8-sig").splitlines():
        if ln.lstrip().startswith("#"):
            continue
        out.extend(ln.split())
    return out


# Слова, которые чаще бывают обычными словами, чем именами: из встроенного
# словаря не берутся вообще (в names.txt их можно добавить вручную)
AMBIGUOUS = {
    "вера", "надежда", "любовь", "слава", "тема", "лев", "мир", "роза", "лада", "пол",
    "венера", "алмаз", "ислам", "улан", "ай", "жан",
    # английские имена-слова и названия мест
    "will", "may", "june", "april", "august", "grace", "hope", "faith", "joy", "rose",
    "ivy", "holly", "iris", "jade", "amber", "ruby", "pearl", "crystal", "summer",
    "autumn", "dawn", "sky", "river", "rain", "storm", "angel", "chase", "hunter",
    "mason", "taylor", "cooper", "parker", "carter", "bishop", "major", "prince",
    "king", "art", "bill", "frank", "rich", "guy", "earl", "max", "ada", "alexa",
    "genesis", "serenity", "harmony", "melody", "destiny", "trinity", "willow",
    "hazel", "violet", "olive", "daisy", "poppy", "florence", "nova", "austin",
    "jordan", "lincoln", "hudson", "christian", "virginia", "sydney", "paris",
    "chelsea", "phoenix", "raven", "sage", "ash", "gray", "grey", "dean", "miles",
    "sunny", "cash", "price", "hero", "ace", "neo", "jasper", "easton",
}

# Имена, которые со строчной буквы — обычные слова: ищем их только с заглавной
LOWER_AMBIGUOUS = {
    "мина", "дана", "мира", "соня", "роман", "султан", "батыр",
    # «по абая» (улица Абая — почти в каждом городе РК), «то ли», «на аллею», «день валентина», «никто нини»,
    # «варя суп», «канат», «абылай хана» (улица)
    "абай", "толя", "алла", "валентина", "валентин", "нина", "абылай", "варя", "канат",
    # «лука» (лук), «лиана», «омар», «талант», «булат», «резеда», «ник», «том», «курт»,
    # «ава» (аватарка), «эка», «жора» (обжора), «тома» (тома книг), «ян»
    "лука", "лиана", "омар", "талант", "булат", "резеда", "ник", "том", "курт", "ава",
    "эка", "жора", "тома", "ян",
    # «педро» (жаргон), «тим» (команда), «сырым» (сырой)
    "педро", "тим", "сырым",
}
# метки, уже вставленные в текст: [ИМЯ_3], [НИК_1], [Человек А]
PLACEHOLDER_ANY_RE = re.compile(r"\[[А-ЯЁ]+(?:_\d+)?\]|\[Человек [^\]]+\]")

# Отдельные падежные формы-омонимы: «марка машины», но «про марк?» — имя
LOWER_STOP_FORMS = {"марка", "марку", "марки", "марке", "маркой", "марок", "тоне"}

ENDINGS_A = ["а", "ы", "и", "е", "у", "ой", "ою", "ей"]
ENDINGS_YA = ["я", "и", "е", "ю", "ей", "ею"]

# Формы имён, которые почти всегда обычные слова — в любом регистре
# («Любой ценой», «майка», «филе», «гены», «ники»)
STOP_FORMS = {"любой", "люби", "любою", "филе", "гены", "майка", "майку", "майке", "майки",
              "майкой", "ники", "ников", "таланты", "талантов"}
ENDINGS_CONS = ["", "а", "у", "ом", "ем", "е", "ым", "ой", "ы", "ых", "ыми"]


def name_forms(name: str) -> set[str]:
    """Падежные формы имени/фамилии (в нижнем регистре, ё→е, казахские буквы → русские)."""
    n = norm(name)
    forms = {n}
    if is_latin(n):
        return forms
    if n.endswith("ий"):
        stem = n[:-1]
        forms |= {stem + e for e in ["й", "я", "ю", "ем", "е", "и"]}
    elif n.endswith("й") or n.endswith("ь"):
        stem = n[:-1]
        forms |= {stem + e for e in ["я", "ю", "ем", "е", "и"]}
    elif n.endswith("ия"):
        stem = n[:-1]
        forms |= {stem + e for e in ["и", "ю", "ей", "ею"]}
    elif n[-1] == "а":
        stem = n[:-1]
        forms |= {stem + e for e in ENDINGS_A}
    elif n[-1] == "я":
        # Надя → Нади, Наде, Надю, Надей (не «нада»); Тоня → Тони (не «тона»)
        stem = n[:-1]
        forms |= {stem + e for e in ENDINGS_YA}
    elif n[-1] not in "аеёиоуыэюя":
        forms |= {n + e for e in ENDINGS_CONS}
    return forms


SURNAME_RE = re.compile(
    r"(?:"
    r"(?:ов|ев|ёв|ин|ын)(?:а|у|ым|ой|ом|е|ых)?"
    r"|(?:ск|цк)(?:ий|ая|ого|ой|ому|им|ую)"
    r"|(?:енко|ук|юк|ян|дзе|швили|улы|кызы)"
    r"|(?:ович|евич|ич)(?:а|у|ем|е)?"
    r"|(?:овн|евн|ичн)(?:а|ы|е|у|ой)"
    r"|(?:ov|ev|in|ova|eva|ina|sky|skiy|skaya|enko|uly|kyzy)"
    r")$",
    re.IGNORECASE,
)

PATRONYMIC_RE = re.compile(
    r"..(?:ұлы|улы|уулу|қызы|кызы|ғызы|гызы|угли|ўғли|оглы|ович|евич|овна|евна|ична|инична)(?:а|у|ем|е|ой|ы)?$",
    re.IGNORECASE,
)
STRETCH_RE = re.compile(r"([аеёиоуыэюяәөұүіАЕЁИОУЫЭЮЯӘӨҰҮІ])\1+")

WORD_RE = re.compile(r"[^\W\d_]+")
LATIN_WORD_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]{3,}(?![A-Za-z])")
LATIN_IDENT_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]{5,}(?![A-Za-z0-9])")


class NameIndex:
    """Знает все имена и решает, является ли слово именем."""

    def __init__(self) -> None:
        self.participant_forms: dict[str, str] = {}   # форма -> метка участника
        self.participant_prefixes: dict[str, str] = {}
        self.dict_forms: dict[str, str] = {}          # форма -> каноническое имя
        self.prefixes: dict[str, str] = {}            # основа -> каноническое имя
        self.user_canon: set[str] = set()             # имена из names.txt и участники чата
        self.group: dict[str, str] = {}               # имя -> «человек» (строка names.txt)
        self.group_label: dict[str, str] = {}         # «человек» -> «Человек А/Б»
        self.keep: set[str] = set()
        # встроенные имена, которые в этом чате хоть раз написаны с заглавной:
        # их ищем и со строчной («ерлан придет»)
        self.confirmed: set[str] = set()
        self.confirmed_latin: list[str] = []

    # ---------- наполнение ----------
    def add_participant(self, display: str, label: str) -> None:
        for tok in WORD_RE.findall(display or ""):
            if len(tok) < 3:
                continue
            for v in latin_variants(tok) | {tok, lat2cyr(tok) if is_latin(tok) else tok}:
                for f in name_forms(v):
                    self.participant_forms[f] = label
                st = name_stem(norm(v))
                if len(st) >= 5 and not is_latin(st):
                    self.participant_prefixes[st] = label

    def add_dict_name(self, name: str, user: bool = False, group: str | None = None) -> None:
        name = name.strip()
        if len(name) < 2:
            return
        canon = norm(name)
        if not user and canon in AMBIGUOUS:
            return
        if canon in self.keep:
            return
        grp = group or canon
        if user:
            self.group[canon] = grp
            self.user_canon.add(canon)
        else:
            self.group.setdefault(canon, grp)
        variants = {name}
        if is_latin(name) and user:
            # только для имён из names.txt: Aigerim → Айгерим. Для английского словаря
            # не делаем, иначе Dan → «дан», Will → «вилл»
            variants.add(lat2cyr(name))
        for v in variants:
            for f in name_forms(v):
                if user:
                    self.dict_forms[f] = canon
                else:
                    self.dict_forms.setdefault(f, canon)
        for lat in latin_variants(name):
            if user:
                self.dict_forms[lat] = canon
            else:
                self.dict_forms.setdefault(lat, canon)
        if user and not is_latin(name):
            st = name_stem(canon)
            if len(st) >= 5:
                self.prefixes[st] = canon

    def add_person(self, names: list[str]) -> None:
        """Одна строка names.txt = один человек со всеми вариантами имени."""
        names = [n.strip() for n in names if n.strip()]
        if not names:
            return
        grp = norm(names[0])
        for n in names:
            label = self.participant_forms.get(norm(n))
            if label:
                self.group_label[grp] = label
        for n in names:
            self.add_dict_name(n, user=True, group=grp)

    def confirm_from_text(self, text: str) -> None:
        for m in WORD_RE.finditer(text):
            w = m.group(0)
            if w[0].isupper():
                canon = self.dict_forms.get(norm(w))
                if canon:
                    self.confirmed.add(canon)

    def finalize(self) -> None:
        lat: set[str] = set()
        for c in self.confirmed | self.user_canon:
            lat |= latin_variants(c)
        lat |= {f for f in self.participant_forms if is_latin(f)}
        self.confirmed_latin = sorted((x for x in lat if len(x) >= 5), key=len, reverse=True)

    # ---------- поиск ----------
    @staticmethod
    def _by_prefix(lw: str, table: dict[str, str]) -> str | None:
        if not table:
            return None
        for n in range(len(lw), 4, -1):
            hit = table.get(lw[:n])
            if hit:
                return hit
        return None

    def lookup(self, word: str) -> tuple[str, str] | None:
        """('P', 'Человек А') — участник; ('N', ключ) — другой человек; None — не имя."""
        hit = self._lookup(word)
        if hit is None and not is_latin(word):
            # растянутые гласные: Ивааан, Машааа, Серииик
            squeezed = STRETCH_RE.sub(r"\1", word)
            if squeezed != word:
                hit = self._lookup(squeezed)
        return hit

    def _lookup(self, word: str) -> tuple[str, str] | None:
        lw = norm(word)
        if lw in STOP_FORMS or (word[0].islower() and lw in LOWER_STOP_FORMS):
            return None
        if lw in self.keep:
            return None
        label = self.participant_forms.get(lw)
        if label is None and not is_latin(word):
            label = self._by_prefix(lw, self.participant_prefixes)
        if label:
            return ("P", label)
        # кандидаты: точная форма (в т.ч. из встроенного словаря) и основа имени из names.txt
        # («данилка» — может быть и формой из словаря, и уменьшительным от имени из names.txt)
        candidates = [self.dict_forms.get(lw)]
        if not is_latin(word):
            candidates.append(self._by_prefix(lw, self.prefixes))
        canon = None
        for c in candidates:
            if c is None:
                continue
            # со строчной ищем все кириллические имена, кроме слов-омонимов
            if not word[0].isupper() and (is_latin(word) or c in LOWER_AMBIGUOUS):
                continue
            canon = c
            break
        if canon is None:
            return None
        grp = self.group.get(canon, canon)
        if grp in self.group_label:
            return ("P", self.group_label[grp])
        return ("N", grp)


# Нұрлан = Нурлан, Әсел = Асел: казахские буквы сравниваем как русские
_KZ_FOLD = str.maketrans("ёәғқңөұүһі", "еагкноуухи")


def norm(word: str) -> str:
    return word.lower().translate(_KZ_FOLD)


def name_stem(n: str) -> str:
    if n.endswith(("ий", "ия")):
        return n[:-2]
    if n and n[-1] in "аеёиоуыэюяйь":
        return n[:-1]
    return n


def latin_variants(word: str) -> set[str]:
    """Латинские написания: Ахмет → akhmet, ahmet; Яна → yana, iana."""
    if is_latin(word):
        return {word.lower()}
    base = cyr2lat(word)
    out = {base}
    for a, b in (("kh", "h"), ("zh", "j"), ("ya", "ia"), ("yu", "iu"), ("ts", "c"), ("y", "i")):
        out |= {v.replace(a, b) for v in list(out)}
    return out


def trie_pattern(words) -> str:
    """Одна регулярка на тысячи строк: быстрее, чем «a|b|c|…»."""
    trie: dict = {}
    for w in words:
        node = trie
        for ch in w:
            node = node.setdefault(ch, {})
        node[""] = True

    def build(node: dict) -> str:
        end = "" in node
        alts = [re.escape(ch) + build(sub) for ch, sub in sorted(node.items()) if ch != ""]
        if not alts:
            return ""
        body = alts[0] if len(alts) == 1 else "(?:" + "|".join(alts) + ")"
        if end:
            return "(?:" + body + ")?"
        return body

    sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))
    return build(trie) if trie else ""


# --------------------------------------------------------------------------
# Регулярки для секретов и персональных данных
# --------------------------------------------------------------------------

PEM_RE = re.compile(
    r"-----BEGIN [A-Z ]*?(?:PRIVATE KEY|CERTIFICATE)-----.*?-----END [A-Z ]*?-----",
    re.S,
)
URL_RE = re.compile(
    r"(?i)\b(?:https?|ftp|wss?|postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s<>\"'`]+"
)
URL_KEEP_HOST = re.compile(r"(?i)^[a-z+]+://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::\d+)?(?:/|$)")
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)*\.[A-Za-z]{2,}")

TOKEN_PREFIX_RE = re.compile(
    r"\b(?:"
    r"sb_(?:publishable|secret)_[\w\-]{8,}"
    r"|sk-(?:ant-|proj-)?[\w\-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[\w]{20,}"
    r"|glpat-[\w\-]{16,}"
    r"|xox[abprs]-[\w\-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|AIza[\w\-]{30,}"
    r"|ya29\.[\w\-]{20,}"
    r"|eyJ[\w\-]{8,}\.[\w\-]{8,}\.[\w\-]{8,}"
    r"|\d{8,10}:AA[\w\-]{30,}"  # токен Telegram-бота
    r")"
)

SECRET_KV_RE = re.compile(
    r"""(?ix)
    (?P<key>
        [A-Za-z0-9_.\-]*?
        (?:secret|token|(?<![A-Za-z])pass(?:w(?:or)?d)?|pwd|api[_-]?key|access[_-]?key
          |private[_-]?key|anon[_-]?key|_key|credential|authorization|auth[_-]?token|cookie
          |session[_-]?(?:id|key|secret|token))
        [A-Za-z0-9_.\-]*
      | пароль | пароля | пасс | токен | ключ | секрет | логин | login
      | пин(?:-?код)? | pin | cvv | cvc | код\s+доступа
    )
    (?P<sep>[ \t]*(?:=>|=|:)[ \t]*|[ \t]+(?:—|–|-)[ \t]+)
    (?P<q>["'`]?)
    (?P<val>[^\s"'`<>,;()\[\]{}]+)
    (?P=q)
    """
)
ID_KV_RE = re.compile(r"\b(?P<key>[A-Z0-9_]*_ID)(?P<sep>[ \t]*=[ \t]*)(?P<q>[\"']?)(?P<val>[^\s\"']+)(?P=q)")
KV_STOP = {
    "true", "false", "null", "none", "nil", "undefined", "string", "number",
    "boolean", "await", "new", "the", "and", "or", "is", "required", "optional",
    "bearer", "basic", "env", "yes", "no", "on", "off", "...", "…",
}
KV_SKIP_VAL = re.compile(
    r"^(?:\.\.\.|…|\*+|x{3,}|<.*|your[-_].*|process\.|Deno\.|os\.|import\.|self\.|this\.|env\.|req\.|ctx\.|config\.|settings\.)",
    re.I,
)

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
HEX_RE = re.compile(r"(?<![\w])[0-9a-fA-F]{24,}(?![\w])")
B64_RE = re.compile(r"(?<![\w+/])[A-Za-z0-9+/]{32,}={0,2}(?![\w+/=])")
PROJECT_REF_RE = re.compile(r"(?<![A-Za-z0-9])[a-z]{20}(?![A-Za-z0-9])")
SPECIALS = set("!@#$%^&*+~?")
RANDOM_TOKEN_RE = re.compile(r"(?<![\w!@#$%^&*+~?\-])[A-Za-z0-9!@#$%^&*+~?_\-]{8,128}(?![\w!@#$%^&*+~?\-])")
TECH_OK = re.compile(
    r"^(?:sha\d+|md5|utf-?\d+|base\d+(?:url)?|es\d{4}|ipv[46]|oauth\d|http\d|x86(?:_64)?|win\d+|"
    r"py(?:thon)?\d+|node\d+|php\d+|ubuntu\d+|v\d+(?:\.\d+)*|i18n|l10n|k8s|mp[34]|h26[45]|"
    r"\d+(?:px|ms|gb|mb|kb|rem|em|vh|vw|fps|kbps))$",
    re.I,
)

NUMERIC_RE = re.compile(r"(?<![\w+\-.:/])(\+?\(?\d(?:[\d \-()]*\d)?)(?![\w\-]|[.:]\d)")
DATE_IN_RE = re.compile(r"(?:19|20)\d{2}-\d{2}-\d{2}|\d{2}-\d{2}-(?:19|20)\d{2}")
LOCAL_PHONE_RE = re.compile(r"^\d{3}[ \-]\d{2}[ \-]\d{2}$")

TLDS = (
    "com|net|org|ru|kz|uz|kg|by|ua|su|info|biz|io|co|ai|app|dev|me|tech|online|site|"
    "store|shop|xyz|cloud|pro|tv|eu|de|uk|us|ca|fr|es|it|pl|tr|cn|jp|az|am|ge|tj|tm|"
    "space|link|live|life|team|group|agency|studio|digital|world|media|ly|gg|fm|рф|қаз"
)
DOMAIN_RE = re.compile(
    rf"(?i)(?<![\w@.\-/])((?:[a-zа-я0-9](?:[a-zа-я0-9\-]{{0,61}}[a-zа-я0-9])?\.)+(?:{TLDS}))(?![\w\-]|\.\w)"
)
# ссылка без https://: t.me/username, instagram.com/name, site.kz/page
BARE_LINK_RE = re.compile(
    rf"(?i)(?<![\w@.\-/])(?:[a-z0-9](?:[a-z0-9\-]{{0,61}}[a-z0-9])?\.)+(?:{TLDS})/"
    r"[^\s<>\"'`\[\]]*[^\s<>\"'`\[\].,;:!?)»]"
)
DOMAIN_KEEP = {
    "github.com", "google.com", "supabase.com", "supabase.co", "vercel.com",
    "vercel.app", "gmail.com", "youtube.com", "telegram.org", "t.me",
    "npmjs.com", "stackoverflow.com", "openai.com", "anthropic.com", "claude.ai",
    "example.com", "yandex.ru", "mail.ru", "wikipedia.org", "apple.com",
    "microsoft.com", "cloudflare.com", "firebase.google.com", "netlify.app",
}
USER_PATH_RE = re.compile(
    r"(?i)(?:\b[a-z]:\\(?:users|documents and settings)\\|(?<![\w.])/(?:home|users)/)([^\\/\s:*?\"<>|]+)"
)
USER_PATH_SKIP = {"public", "default", "all users", "shared", "user", "username", "<user>", "you"}

# ---- Адреса ----
_CAP = "А-ЯЁӘҒҚҢӨҰҮҺІA-Z"
_NAME_CAP = rf"[«\"]?[{_CAP}][\w\-]*[»\"]?(?:\s+[{_CAP}][\w\-]*[»\"]?){{0,2}}"
_NAME_ANY = rf"[«\"]?\w[\w\-]*[»\"]?(?:\s+[{_CAP}][\w\-]*[»\"]?){{0,2}}"
_HOUSE = r"(?:[ ,]+(?:(?i:д(?:ом)?)\.?\s*)?№?\s*\d+[а-яa-z]?(?:\s*[/\-]\s*\d+[а-яa-z]?)?(?![\w.]\d))?"
_PART = r"(?i:кв(?:артира)?|корп(?:ус)?|к|стр(?:оение)?|подъезд|под|эт(?:аж)?|офис|оф|блок)\.?\s*№?\s*\d+[а-яa-z]?"
_PARTS = rf"(?:[ ,]+{_PART}(?!\w))*"
# сокращения без точки: ул Ленина, мкр Восток-5, ж/к «Солнечный»; с точкой: пр. Мира, пер. Садовый
_ABBR = r"(?i:(?:ул|мкрн?|мкр-н|пр-т|б-р|ж/к|жк)(?![\w/])\.?)"
_ABBR_DOT = r"(?i:(?:пр|просп|пер|наб|пл|ш|бул)\.)"  # «и пр. вещи» — после них нужна заглавная
_FULL = (r"(?i:улиц(?:а|е|у|ы|ей)|проспект(?:а|е|у|ом)?|переул(?:ок|ке|ка|ку)|бульвар(?:а|е|у)?"
         r"|набережн(?:ая|ой|ую)|площад(?:ь|и)|шоссе|микрорайон(?:а|е|у)?|жил(?:ой|ом)\s+комплекс(?:е|а)?"
         r"|аллея|тупик)(?![\w])")
ADDRESS_RE = re.compile(
    rf"(?<![\w])(?:{_ABBR}\s*{_NAME_ANY}|{_ABBR_DOT}\s*{_NAME_CAP}|{_FULL}\s+{_NAME_CAP}){_HOUSE}{_PARTS}"
    # казахский порядок и «Восток-5 мкр»: Бейбітшілік көшесі 12, Тәуелсіздік даңғылы 5
    rf"|(?<![\w])[{_CAP}][\w\-]*\s+(?i:көшесі|даңғылы|шағын\s*ауданы|мкрн?)(?![\w]){_HOUSE}{_PARTS}"
    # «микрорайон 81А», «в микрорайоне 8Б, д. 12»
    rf"|(?<![\w])(?i:микрорайон(?:а|е|у|ом)?)\s*№?\s*\d+[а-яА-ЯёЁa-zA-Z]?(?![\w]){_HOUSE}{_PARTS}"
)
# «д. 5, кв. 12», «дом 15 кв 3», «квартира 47» без названия улицы
APARTMENT_RE = re.compile(
    rf"(?<![\w])(?:(?i:дом|д\.)\s*№?\s*\d+[а-яa-z]?(?:\s*/\s*\d+)?(?:[ ,]+{_PART}(?!\w))+"
    r"|(?<!\d\s)(?<!\d)(?i:кв(?:артира)?)\.?\s*№?\s*\d{1,4}[а-яa-z]?(?![\w.,]\d))"  # «1 кв 2026» — квартал
)
COORD_RE = re.compile(r"(?<![\d.])-?\d{1,2}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}(?!\d)")

# ---- Документы ----
_DOC_KEY = (r"(?i:паспорт\w*|удостоверени\w*|уд\.?\s?л(?:ичности)?\.?|удл|id[\s-]?карт\w*|id\s*card"
            r"|passport|свидетельств\w*|полис\w*|снилс|инн|бин|иин|водительск\w*\s+прав\w*|в/у|ву"
            r"|серии|серия|номер\s+документа|документ\w*|договор\w*)")
DOC_RE = re.compile(
    rf"(?<![\w])(?P<key>{_DOC_KEY})(?![\w])(?P<gap>[^\d\n]{{0,25}}?)"
    r"(?P<val>(?:[A-ZА-ЯЁ]{1,3}\s?)?\d[\d \-№]{4,16}\d)(?![\w])"
)
# N12345678 (паспорт РК), AB1234567 — без ключевого слова
DOC_CODE_RE = re.compile(r"(?<![\w\-])[A-Z]{1,2}\d{7,8}(?![\w\-])")
# госномера: 777ABC02 (РК), А123ВС777 (РФ)
PLATE_RE = re.compile(
    r"(?<![\w])(?:\d{3}\s?[A-Z]{2,3}\s?\d{2}|[АВЕКМНОРСТУХABEKMHOPCTYX]\d{3}[АВЕКМНОРСТУХABEKMHOPCTYX]{2}\s?\d{2,3})(?![\w])"
)
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,31})\b(?![/.\-]\w)")
CONTACT_PH_RE = re.compile(r"\[(?:ПОЧТА|ТЕЛЕФОН|ЛОГИН|НИК)_\d+\]")
CRED_WORD_RE = re.compile(r"(?i)(?<![\w])(логин|login|пароль|password|passwd|pass|pwd|пасс)(?![\w])")
CRED_LABEL_END_RE = re.compile(r"(?i)(пароль|password|passwd|pass|pwd|пасс)\s*[:=\-—]?\s*$")
SAME_LINE_PW_RE = re.compile(
    r"(\[(?:ПОЧТА|ТЕЛЕФОН|ЛОГИН)_\d+\])([ \t]*[|/:;,]+[ \t]*|[ \t]+)([^\s\[\]]{4,64})(?=\s|$)"
)
STANDALONE_PW_RE = re.compile(r"^[A-Za-z]{3,}[_.@!#$%\-]?\d{2,}[!@#$%*]?$")
LONG_DIGITS_RE = re.compile(r"(?<!\d)(?<!_)\d{9,}(?!\d)")
PLACEHOLDER_RE = re.compile(r"^\[[А-ЯЁ]+(?:_\d+)?\]$|^\[Человек [^\]]+\]$")


def entropy(s: str) -> float:
    c = Counter(s)
    n = len(s)
    return -sum(v / n * math.log2(v / n) for v in c.values())


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def looks_like_password(tok: str, strict: bool = True) -> bool:
    if PLACEHOLDER_RE.match(tok) or not (3 <= len(tok) <= 64):
        return False
    if re.search(r"[А-Яа-яЁё\s]", tok):
        return False
    if not strict:
        return True
    has_letter = bool(re.search(r"[A-Za-z]", tok))
    has_digit = bool(re.search(r"\d", tok))
    has_special = any(ch in SPECIALS or ch == "_" or ch == "." for ch in tok)
    return len(tok) >= 4 and has_letter and (has_digit or has_special)


def is_random_token(tok: str) -> bool:
    """Похоже ли слово на сгенерированный пароль/ключ."""
    if TECH_OK.match(tok):
        return False
    letters = sum(ch.isalpha() for ch in tok)
    digits = sum(ch.isdigit() for ch in tok)
    upper = sum(ch.isupper() for ch in tok)
    lower = sum(ch.islower() for ch in tok)
    special = sum(ch in SPECIALS for ch in tok)
    # 1) в одном «слове» (без _ - ) буквы вперемешку с ≥3 цифрами: Summer2024pass, x7k2m9q4z1
    for seg in re.split(r"[_\-]", tok):
        if len(seg) >= 8 and sum(c.isdigit() for c in seg) >= 3 and sum(c.isalpha() for c in seg) >= 2:
            if not TECH_OK.match(seg):
                return True
    # 2) три+ класса символов включая спецсимволы: x9pq2w&7K!mZ
    classes = sum(x > 0 for x in (upper, lower, digits, special))
    if special and digits and letters >= 2 and classes >= 3 and len(tok) >= 8 and entropy(tok) >= 3.0:
        return True
    # 3) хаотичная смена регистра/цифр: aB3dE7fG, Qw8eRt5yUi
    if upper and lower and digits and letters >= 4:
        core = re.sub(r"[_\-]", "", tok)
        trans = sum(
            1 for a, b in zip(core, core[1:])
            if (a.isupper(), a.islower(), a.isdigit()) != (b.isupper(), b.islower(), b.isdigit())
        )
        if trans / max(1, len(core) - 1) >= 0.35 and len(core) >= 8:
            return True
    return False


# --------------------------------------------------------------------------
# Анонимизатор
# --------------------------------------------------------------------------


class Anonymizer:
    def __init__(self, vault: Vault, names: NameIndex, hide_terms: list[str],
                 seeds: dict[str, set[str]], use_ner: bool, extra_hide: list[str] = ()) -> None:
        self.v = vault
        self.names = names
        # self.hide_base: форма → исходное слово из hide.txt (чтобы у всех форм была одна метка)
        self.hide_base: dict[str, str] = {}
        prefixes: dict[str, str] = {}
        for raw in hide_terms:
            t = " ".join(raw.strip().lower().split())
            if not t:
                continue
            self.hide_base[t] = t
            head, _, last = t.rpartition(" ")
            if is_latin(last) or not re.fullmatch(r"[^\W\d_]+", last):
                continue
            if not head and len(last) >= 5:
                # одно слово: всё, что с него начинается — Караганде, карагандинские
                prefixes[name_stem(last) if len(name_stem(last)) >= 5 else last] = t
            elif head and len(last) >= 3:
                # фраза: падежи последнего слова — в Каспий банке
                # (короткое одиночное слово вроде «Мира» — только точно, иначе заденет «мир», «миру»)
                for f in name_forms(last):
                    self.hide_base.setdefault(f"{head} {f}" if head else f, t)
        for raw in extra_hide:  # названия каналов и чатов — только точное совпадение
            t = " ".join(raw.strip().lower().split())
            if t:
                self.hide_base.setdefault(t, t)
        self.hide_prefixes = prefixes
        parts = []
        if prefixes:
            parts.append("(?:" + trie_pattern(prefixes) + r")[^\W\d_]*")
        if self.hide_base:
            parts.append(trie_pattern(sorted(self.hide_base)))
        self.hide_re = (re.compile(r"(?i)(?<![\w])(?:" + "|".join(parts) + r")(?![\w])")
                        if parts else None)
        self.seed_map: dict[str, str] = {}
        for cat, vals in seeds.items():
            for val in vals:
                if len(val) >= 4:
                    self.seed_map.setdefault(val, cat)
        self.seed_re = re.compile(trie_pattern(self.seed_map)) if self.seed_map else None
        self.ner = self._load_ner() if use_ner else None

    def _hide_key(self, found: str) -> str:
        low = " ".join(found.lower().split())
        if low in self.hide_base:
            return self.hide_base[low]
        for p in sorted(self.hide_prefixes, key=len, reverse=True):
            if low.startswith(p):
                return self.hide_prefixes[p]
        return low

    # ---------- NER (необязательно) ----------
    @staticmethod
    def _load_ner():
        try:
            from natasha import Doc, NewsEmbedding, NewsNERTagger, Segmenter  # type: ignore
        except Exception:
            return None
        emb = NewsEmbedding()
        return {"Doc": Doc, "seg": Segmenter(), "tagger": NewsNERTagger(emb)}

    def _ner_spans(self, text: str) -> list[tuple[int, int]]:
        if not self.ner or not re.search(r"[А-Яа-яЁё]", text):
            return []
        doc = self.ner["Doc"](text)
        doc.segment(self.ner["seg"])
        doc.tag_ner(self.ner["tagger"])
        return [(s.start, s.stop) for s in doc.spans if s.type == "PER"]

    # ---------- отдельные шаги ----------
    def _sub(self, regex, text: str, cat: str, group: int = 0, check=None) -> str:
        def repl(m):
            val = m.group(group)
            if check and not check(val):
                return m.group(0)
            if PLACEHOLDER_RE.match(val):
                return m.group(0)
            start, end = m.start(group) - m.start(0), m.end(group) - m.start(0)
            whole = m.group(0)
            return whole[:start] + self.v.tag(cat, val) + whole[end:]
        return regex.sub(repl, text)

    def _urls(self, text: str) -> str:
        def repl(m):
            url = m.group(0)
            trail = ""
            while url and url[-1] in ".,;:!?)»]}'\"":
                trail = url[-1] + trail
                url = url[:-1]
            if URL_KEEP_HOST.match(url):
                return m.group(0)
            return self.v.tag("ССЫЛКА", url) + trail
        return URL_RE.sub(repl, text)

    def _kv(self, regex, text: str, cat: str) -> str:
        def repl(m):
            val = m.group("val")
            low = val.lower()
            if (low in KV_STOP or KV_SKIP_VAL.match(val) or PLACEHOLDER_RE.match(val)
                    or re.fullmatch(r"[а-яёәғқңөұүһі\-]+", low)
                    # SESSION_KEY='app_user_cache' — имя ключа в коде, а не секрет
                    or (re.fullmatch(r"[A-Z0-9_]*KEY", m.group("key"))
                        and re.fullmatch(r"[a-z]+(?:_[a-z]+)+", val))
                    or (m.group("sep").strip() in ("-", "—", "–")
                        and not (re.search(r"\d", val) or is_random_token(val)))):
                return m.group(0)
            return m.group("key") + m.group("sep") + m.group("q") + self.v.tag(cat, val) + m.group("q")
        return regex.sub(repl, text)

    def _numbers(self, text: str) -> str:
        def repl(m):
            s = m.group(1)
            if s.startswith("(") and ")" not in s:  # «(87001234567)» — скобка не часть номера
                return "(" + classify(s[1:])
            return classify(s)

        def classify(s):
            digits = re.sub(r"\D", "", s)
            n = len(digits)
            formatted = bool(re.search(r"[ \-()]", s))
            if DATE_IN_RE.search(s):
                return s
            if formatted and n == 7 and LOCAL_PHONE_RE.match(s.strip("()")):
                return self.v.tag("ТЕЛЕФОН", s)
            if n < 9:
                return s
            if 13 <= n <= 19 and luhn_ok(digits):
                return self.v.tag("КАРТА", s)
            if n >= 13:
                return self.v.tag("НОМЕР", s)
            if s.startswith("+") and n >= 10:
                return self.v.tag("ТЕЛЕФОН", s)
            if n == 12:
                return self.v.tag("ТЕЛЕФОН" if formatted else "ИИН", s)
            if n == 11 and (digits[0] in "78" or formatted):
                return self.v.tag("ТЕЛЕФОН", s)
            if n == 10 and (digits[0] in "79" or formatted):
                return self.v.tag("ТЕЛЕФОН", s)
            return self.v.tag("НОМЕР", s)
        return NUMERIC_RE.sub(repl, text)

    def _random_tokens(self, text: str) -> str:
        def repl(m):
            tok = m.group(0)
            return self.v.tag("СЕКРЕТ", tok) if is_random_token(tok) else tok
        return RANDOM_TOKEN_RE.sub(repl, text)

    def _project_refs(self, text: str) -> str:
        def repl(m):
            tok = m.group(0)
            vowels = sum(ch in "aeiou" for ch in tok)
            return self.v.tag("ИД", tok) if vowels / len(tok) < 0.4 else tok
        return PROJECT_REF_RE.sub(repl, text)

    def _domains(self, text: str) -> str:
        def repl(m):
            d = m.group(1)
            if d.lower() in DOMAIN_KEEP:
                return d
            return self.v.tag("ДОМЕН", d)
        return DOMAIN_RE.sub(repl, text)

    def _context_passwords(self, text: str, prev_context: str = "") -> str:
        # «[ТЕЛЕФОН_1] Summer2024pass» в одной строке
        def same_line(m):
            tok = m.group(3)
            if looks_like_password(tok):
                return m.group(1) + m.group(2) + self.v.tag("ПАРОЛЬ", tok)
            return m.group(0)
        text = SAME_LINE_PW_RE.sub(same_line, text)
        # «почта\nпароль» на соседних строках (или в соседних сообщениях)
        lines = text.split("\n")
        prev = prev_context.strip().split("\n")[-1].strip() if prev_context.strip() else ""
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s:
                # отдельная строка вида Word_2026 / qwerty123 / City_01 — типичный пароль
                if (" " not in s and len(s) >= 6 and STANDALONE_PW_RE.match(s)
                        and not TECH_OK.match(s)):
                    lines[i] = ln.replace(s, self.v.tag("ПАРОЛЬ", s))
                elif prev and " " not in s and not PLACEHOLDER_RE.match(s):
                    label_only = bool(CRED_LABEL_END_RE.search(prev))
                    trigger = label_only or CONTACT_PH_RE.search(prev) or CRED_WORD_RE.search(prev)
                    if trigger and looks_like_password(s, strict=not label_only):
                        lines[i] = ln.replace(s, self.v.tag("ПАРОЛЬ", s))
                prev = lines[i].strip()
        return "\n".join(lines)

    def _latin_nicks(self, text: str) -> str:
        """anna_2005, ivanpetrov … — логины, содержащие известное имя."""
        nm = self.names

        def exact(m):
            # anna_2005, ivan.k: имя латиницей внутри ника, в любом регистре
            tok = m.group(0)
            low = tok.lower()
            if low in nm.keep:
                return tok
            if low in nm.participant_forms:
                return f"[{nm.participant_forms[low]}]"
            canon = nm.dict_forms.get(low)
            if canon and canon in nm.user_canon:
                return self._label(nm.lookup(tok[0].upper() + tok[1:]) or ("N", canon), tok)
            return tok
        text = LATIN_WORD_RE.sub(exact, text)
        if not nm.confirmed_latin:
            return text

        def repl(m):
            tok = m.group(0)
            low = tok.lower()
            if low in self.names.participant_forms or low in self.names.dict_forms:
                return tok  # само имя обработает _names
            if any(n in low for n in self.names.confirmed_latin):
                return self.v.tag("НИК", tok)
            return tok
        return LATIN_IDENT_RE.sub(repl, text)

    @staticmethod
    def _with_surname(text: str, words: list, idx: int) -> tuple[int, int]:
        """Расширяет найденное имя на соседние фамилию и отчество."""
        start, end = words[idx].start(), words[idx].end()
        for j in (idx + 1, idx + 2):
            if j < len(words):
                nxt = words[j]
                if (text[end:nxt.start()] in (" ", " ") and nxt.group(0)[0].isupper()
                        and SURNAME_RE.search(nxt.group(0))):
                    end = nxt.end()
                    continue
            break
        if idx > 0:
            prv = words[idx - 1]
            if (text[prv.end():start] in (" ", " ") and prv.group(0)[0].isupper()
                    and SURNAME_RE.search(prv.group(0))):
                start = prv.start()
        return start, end

    def _label(self, hit: tuple[str, str], word: str) -> str:
        kind, val = hit
        return f"[{val}]" if kind == "P" else self.v.tag("ИМЯ", word, key=val)

    def _names(self, text: str) -> str:
        spans: list[tuple[int, int, str]] = []
        # слова внутри уже поставленных меток ([НИК_1], [Человек А]) не трогаем
        inside = [(p.start(), p.end()) for p in PLACEHOLDER_ANY_RE.finditer(text)]
        words = [w for w in WORD_RE.finditer(text)
                 if not any(s <= w.start() < e for s, e in inside)]
        for idx, m in enumerate(words):
            hit = self.names.lookup(m.group(0))
            if hit:
                start, end = self._with_surname(text, words, idx)
                spans.append((start, end, self._label(hit, m.group(0))))
            elif m.group(0)[0].isupper() and PATRONYMIC_RE.search(m.group(0)):
                # Серікұлы Нұрлан, Анна Сергеевна, Ерланқызы — отчество
                # почти всегда часть ФИО: прихватываем соседние слова с заглавной
                start, end = m.start(), m.end()
                for j in (idx + 1, idx + 2):
                    if j < len(words) and text[end:words[j].start()] in (" ", " ") \
                            and words[j].group(0)[0].isupper():
                        end = words[j].end()
                    else:
                        break
                for j in (idx - 1, idx - 2):
                    if j >= 0 and text[words[j].end():start] in (" ", " ") \
                            and words[j].group(0)[0].isupper():
                        start = words[j].start()
                    else:
                        break
                spans.append((start, end, self.v.tag("ИМЯ", text[start:end], key=norm(text[start:end]))))
        for s, e in self._ner_spans(text):
            frag = text[s:e]
            if "[" in frag:
                continue
            first = WORD_RE.findall(frag)
            if not first or norm(first[0]) in self.names.keep:
                continue
            hit = self.names.lookup(first[0]) or ("N", norm(first[0]))
            spans.append((s, e, self._label(hit, frag)))
        if not spans:
            return text
        spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
        out, pos = [], 0
        for s, e, rep in spans:
            if s < pos:
                continue
            out.append(text[pos:s])
            out.append(rep)
            pos = e
        out.append(text[pos:])
        return "".join(out)

    # ---------- общий конвейер ----------
    def redact(self, text: str, prev_context: str = "") -> str:
        if not text:
            return text
        if self.seed_re:
            text = self.seed_re.sub(lambda m: self.v.tag(self.seed_map[m.group(0)], m.group(0)), text)
        text = self._sub(PEM_RE, text, "СЕКРЕТ")
        text = self._urls(text)
        text = self._sub(BARE_LINK_RE, text, "ССЫЛКА")
        text = self._sub(EMAIL_RE, text, "ПОЧТА")
        text = self._sub(USER_PATH_RE, text, "НИК", group=1,  # C:\Users\ivan\…
                         check=lambda u: u.lower() not in USER_PATH_SKIP)
        text = self._sub(COORD_RE, text, "КООРДИНАТЫ")
        text = self._sub(ADDRESS_RE, text, "АДРЕС", check=lambda a: len(a.strip()) > 3)
        text = self._sub(APARTMENT_RE, text, "АДРЕС")
        text = self._sub(DOC_RE, text, "ДОКУМЕНТ", group="val",
                         check=lambda v: len(re.sub(r"\D", "", v)) >= 6)
        text = self._sub(DOC_CODE_RE, text, "ДОКУМЕНТ")
        text = self._sub(PLATE_RE, text, "ГОСНОМЕР")
        text = self._sub(TOKEN_PREFIX_RE, text, "СЕКРЕТ")
        text = self._kv(SECRET_KV_RE, text, "СЕКРЕТ")
        text = self._kv(ID_KV_RE, text, "ИД")
        text = self._sub(UUID_RE, text, "ИД")
        text = self._sub(HEX_RE, text, "СЕКРЕТ", check=lambda s: bool(re.search(r"\d", s) and re.search(r"[a-fA-F]", s)))
        text = self._sub(B64_RE, text, "СЕКРЕТ",
                         check=lambda s: bool(re.search(r"\d", s) and re.search(r"[a-z]", s) and re.search(r"[A-Z]", s)))
        text = self._random_tokens(text)
        text = self._project_refs(text)
        text = self._numbers(text)
        text = self._sub(LONG_DIGITS_RE, text, "НОМЕР")  # номера, приклеенные к буквам
        text = self._domains(text)
        text = self._sub(MENTION_RE, text, "НИК")
        text = self._context_passwords(text, prev_context)
        if self.hide_re:
            text = self.hide_re.sub(lambda m: self.v.tag("СКРЫТО", m.group(0), key=self._hide_key(m.group(0))),
                                    text)
        text = self._latin_nicks(text)
        text = self._names(text)
        return text


# --------------------------------------------------------------------------
# Работа с экспортом
# --------------------------------------------------------------------------


def flatten_text(msg: dict) -> str:
    ents = msg.get("text_entities")
    if isinstance(ents, list) and ents:
        return "".join(e.get("text", "") for e in ents)
    t = msg.get("text", "")
    if isinstance(t, list):
        return "".join(x if isinstance(x, str) else x.get("text", "") for x in t)
    return t or ""


def media_label(msg: dict) -> str | None:
    mt = msg.get("media_type")
    labels = {
        "sticker": "стикер", "video_file": "видео", "voice_message": "голосовое сообщение",
        "audio_file": "аудио", "video_message": "видеосообщение", "animation": "GIF",
    }
    if mt:
        lab = labels.get(mt, mt)
        if mt == "sticker" and msg.get("sticker_emoji"):
            lab += " " + msg["sticker_emoji"]
        return lab
    if "photo" in msg:
        return "фото"
    if "file" in msg or "file_name" in msg:
        return "файл"
    if "contact_information" in msg:
        return "контакт"
    if "location_information" in msg:
        return "геолокация"
    if "poll" in msg:
        return "опрос"
    return None


def collect_seeds(messages: list[dict], names: NameIndex) -> dict[str, set[str]]:
    """Telegram сам размечает телефоны/почты/карты — используем как подсказки."""
    seeds: dict[str, set[str]] = defaultdict(set)
    cat_by_type = {"email": "ПОЧТА", "phone": "ТЕЛЕФОН", "bank_card": "КАРТА", "mention": "НИК"}
    for m in messages:
        for e in m.get("text_entities") or []:
            t, txt = e.get("type"), e.get("text", "")
            if t in cat_by_type and txt:
                seeds[cat_by_type[t]].add(txt)
            elif t == "mention_name" and txt:
                names.add_person([tok for tok in WORD_RE.findall(txt) if len(tok) >= 3])
        ci = m.get("contact_information") or {}
        if ci.get("phone_number"):
            seeds["ТЕЛЕФОН"].add(ci["phone_number"])
        names.add_person([ci[k] for k in ("first_name", "last_name") if ci.get(k)])
    return seeds


# Подписи в Telegram, которые не являются именами («Мама», «Работа»)
GENERIC_WORDS = {
    "мама", "папа", "мамуля", "папуля", "брат", "братик", "сестра", "сестренка",
    "бабушка", "дедушка", "жена", "муж", "сын", "дочь", "дочка", "любимая",
    "любимый", "работа", "мой", "моя", "номер", "новый", "новая", "старый",
    "mom", "mother", "dad", "father", "wife", "husband", "work", "my", "new", "old",
}


def display_tokens(display: str) -> list[str]:
    return [t for t in WORD_RE.findall(display or "") if len(t) >= 3 and norm(t) not in GENERIC_WORDS]


def collect_third_parties(messages: list[dict], labels: dict, names: NameIndex,
                          hide_terms: list[str]) -> dict[str, str]:
    """Имена всех остальных людей из служебных полей — чтобы скрыть их и в тексте.
    Возвращает id → отображаемое имя (для источников пересылок)."""
    people: dict[str, str] = {}
    fields = (("from", "from_id"), ("actor", "actor_id"),
              ("forwarded_from", "forwarded_from_id"), ("saved_from", None), ("author", None))
    for m in messages:
        for nk, ik in fields:
            nm = m.get(nk)
            if not isinstance(nm, str) or not nm.strip():
                continue
            fid = str(m.get(ik) or "") if ik else ""
            if fid in labels:
                continue
            people.setdefault(fid or nm, nm)
    for key, nm in people.items():
        if key.startswith("user"):
            names.add_person(display_tokens(nm))
        elif len(nm.strip()) >= 4:
            hide_terms.append(nm.strip())  # каналы и группы — скрываем название целиком
    return people


def read_list(path: str | None) -> list[str]:
    if not path:
        return []
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8-sig").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def read_people(path: str | None) -> list[list[str]]:
    """names.txt: одна строка — один человек, варианты через запятую."""
    return [[x.strip() for x in re.split(r"[,;]", ln) if x.strip()] for ln in read_list(path)]


def default_file(arg: str | None, name: str) -> str | None:
    """Если файл не указан явно, берём names.txt / hide.txt / keep.txt рядом со скриптом."""
    if arg:
        return arg
    p = Path(__file__).resolve().with_name(name)
    return str(p) if p.exists() else None


def pick_participants(messages: list[dict], a: str | None, b: str | None) -> list[str]:
    counts: Counter = Counter()
    names: dict[str, str] = {}
    for m in messages:
        if m.get("type") == "message" and m.get("from_id"):
            counts[m["from_id"]] += 1
            names.setdefault(m["from_id"], m.get("from") or "")

    def resolve(q: str) -> str:
        ql = q.lower().lstrip("@")
        for fid, nm in names.items():
            if ql in (fid.lower(), fid.lower().replace("user", ""), (nm or "").lower()):
                return fid
        for fid, nm in names.items():
            if ql in (nm or "").lower():
                return fid
        sys.exit(f"Участник «{q}» не найден. Есть: " + ", ".join(f"{n} ({f})" for f, n in names.items()))

    chosen = [resolve(x) for x in (a, b) if x]
    for fid, _ in counts.most_common():
        if len(chosen) >= 2:
            break
        if fid not in chosen:
            chosen.append(fid)
    if len(chosen) < 2:
        sys.exit("В чате меньше двух участников с сообщениями.")
    return chosen


SENTENCE_START_RE = re.compile(r"(?:^|[.!?…\n:;|*#>•«\"(\-—–]\s*|\b[0-9a-f]{7,40}\s+)$")
CAP_WORD_RE = re.compile(r"(?<![\w\[])[А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]{2,}(?![\w\]])")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="Анонимизация экспорта чата Telegram (result.json)")
    ap.add_argument("input", help="путь к result.json из Telegram Desktop")
    ap.add_argument("-o", "--output", help="куда сохранить JSON (по умолчанию <имя>_anon.json рядом)")
    ap.add_argument("--txt", help="дополнительно сохранить переписку простым текстом")
    ap.add_argument("--a", help="кто будет «Человек А»: имя, user-id или его часть (по умолчанию самый активный)")
    ap.add_argument("--b", help="кто будет «Человек Б»")
    ap.add_argument("--label-a", default="Человек А")
    ap.add_argument("--label-b", default="Человек Б")
    ap.add_argument("--names", help="имена для скрытия: строка = человек, варианты через запятую "
                                    "(по умолчанию names.txt рядом со скриптом)")
    ap.add_argument("--hide", help="слова/фразы для скрытия: компании, адреса… (по умолчанию hide.txt)")
    ap.add_argument("--keep", help="слова, которые НЕ являются именами (по умолчанию keep.txt)")
    ap.add_argument("--no-dates", action="store_true", help="убрать даты сообщений")
    ap.add_argument("--no-ner", action="store_true", help="не использовать natasha, даже если установлена")
    ap.add_argument("--suggest", help="сохранить список слов с заглавной буквы, похожих на "
                                      "пропущенные имена, — для дополнения names.txt")
    ap.add_argument("--audit", help="сохранить таблицу замен для проверки (содержит исходные данные!)")
    args = ap.parse_args()

    src = Path(args.input)
    print("Читаю файл…", file=sys.stderr)
    data = json.loads(src.read_text(encoding="utf-8"))
    if "messages" not in data:
        sys.exit("Это не экспорт одного чата: в файле нет поля messages. "
                 "Экспортируйте нужный чат через «⋮ → Экспорт истории чата», формат JSON.")
    messages = data["messages"]

    a_id, b_id = pick_participants(messages, args.a, args.b)
    labels = {a_id: args.label_a, b_id: args.label_b}
    display: dict[str, set[str]] = {}
    for m in messages:
        if m.get("from_id") in labels:
            display.setdefault(m["from_id"], set()).add(m.get("from") or "")
        if m.get("forwarded_from_id") in labels and m.get("forwarded_from"):
            display.setdefault(m["forwarded_from_id"], set()).add(m["forwarded_from"])
    print(f"{args.label_a}: {', '.join(sorted(display.get(a_id, {''})))} ({a_id})", file=sys.stderr)
    print(f"{args.label_b}: {', '.join(sorted(display.get(b_id, {''})))} ({b_id})", file=sys.stderr)

    names_file = default_file(args.names, "names.txt")
    hide_file = default_file(args.hide, "hide.txt")
    keep_file = default_file(args.keep, "keep.txt")
    for f, what in ((names_file, "имена"), (hide_file, "скрываемые слова"), (keep_file, "исключения")):
        if f:
            print(f"{what}: {f}", file=sys.stderr)

    names = NameIndex()
    names.keep = {norm(w) for ln in read_list(keep_file) for w in re.split(r"[,;]", ln) if w.strip()}
    # тексты-метки «Человек А» не должны снова распознаваться как имена
    names.keep |= {norm(w) for lab in labels.values() for w in WORD_RE.findall(lab)}
    for fid, lab in labels.items():
        for d in display.get(fid, ()):
            names.add_participant(" ".join(display_tokens(d)), lab)
    if data.get("type") == "personal_chat" and data.get("name"):
        owner = next((fid for fid in labels if data["name"] in display.get(fid, ())), None)
        if owner:
            names.add_participant(" ".join(display_tokens(data["name"])), labels[owner])
        else:
            names.add_person(display_tokens(data["name"]))
    for person in read_people(names_file):
        names.add_person(person)
    for n in load_builtin_names():
        names.add_dict_name(n)
    hide_terms = read_list(hide_file)
    channel_names: list[str] = []
    people = collect_third_parties(messages, labels, names, channel_names)

    vault = Vault()
    seeds = collect_seeds(messages, names)
    for m in messages:
        names.confirm_from_text(flatten_text(m))
    names.finalize()
    anon = Anonymizer(vault, names, hide_terms, seeds, use_ner=not args.no_ner, extra_hide=channel_names)
    if not args.no_ner and anon.ner is None:
        print("natasha не установлена — имена ищутся по словарю и names.txt.", file=sys.stderr)

    out_msgs, id_map = [], {}
    skipped = Counter()
    suggest: Counter = Counter()
    suggest_example: dict[str, str] = {}
    prev_clean = ""
    total = len(messages)
    for i, m in enumerate(messages, 1):
        if i % 20000 == 0:
            print(f"  обработано {i} из {total}…", file=sys.stderr)
        if m.get("type") != "message":
            skipped["служебные"] += 1
            continue
        fid = m.get("from_id")
        if fid not in labels:
            skipped["другие участники"] += 1
            continue
        new_id = len(out_msgs) + 1
        id_map[m.get("id")] = new_id
        rec: dict = {"id": new_id, "type": "message"}
        if not args.no_dates and m.get("date"):
            rec["date"] = m["date"]
        rec["from"] = labels[fid]
        rec["from_id"] = "A" if fid == a_id else "B"
        if m.get("reply_to_message_id") in id_map:
            rec["reply_to_message_id"] = id_map[m["reply_to_message_id"]]
        fwd_id, fwd_name = m.get("forwarded_from_id"), m.get("forwarded_from")
        if fwd_id or fwd_name or m.get("saved_from"):
            rec["forwarded"] = True
            if fwd_id in labels:
                rec["forwarded_from"] = labels[fwd_id]
            elif fwd_id or fwd_name:
                rec["forwarded_from"] = vault.tag("ЧЕЛОВЕК", str(fwd_name), key=str(fwd_id or fwd_name))
        media = media_label(m)
        if media:
            rec["media"] = media
        text = flatten_text(m)
        poll = m.get("poll") or {}
        if poll.get("question"):
            answers = "; ".join(a.get("text", "") for a in poll.get("answers", []))
            text = (text + "\n" if text else "") + f"Опрос: {poll['question']}" + (f" ({answers})" if answers else "")
        clean = anon.redact(text, prev_context=prev_clean)
        prev_clean = clean
        rec["text"] = clean
        rec["text_entities"] = [{"type": "plain", "text": clean}] if clean else []
        out_msgs.append(rec)
        if args.suggest and clean:
            for w in CAP_WORD_RE.finditer(clean):
                if SENTENCE_START_RE.search(clean[max(0, w.start() - 45):w.start()]):
                    continue
                lw = norm(w.group(0))
                if lw in names.keep:
                    continue
                suggest[w.group(0)] += 1
                suggest_example.setdefault(
                    w.group(0), clean[max(0, w.start() - 40):w.end() + 40].replace("\n", " "))

    result = {
        "name": "Анонимный чат",
        "type": data.get("type", "personal_chat"),
        "participants": [args.label_a, args.label_b],
        "messages": out_msgs,
    }
    out_path = Path(args.output) if args.output else src.with_name(src.stem + "_anon.json")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.txt:
        lines = []
        for r in out_msgs:
            head = f"[{r['date'].replace('T', ' ')}] " if "date" in r else ""
            extra = f"<{r['media']}> " if "media" in r else ""
            fwd = ""
            if r.get("forwarded"):
                fwd = f"(переслано от {r['forwarded_from']}) " if r.get("forwarded_from") else "(переслано) "
            lines.append(f"{head}{r['from']}: {fwd}{extra}{r['text']}".rstrip())
        Path(args.txt).write_text("\n\n".join(lines) + "\n", encoding="utf-8")

    if args.suggest:
        rows = ["# Слова с заглавной буквы не в начале предложения, которые остались в тексте.",
                "# Если среди них есть имена — допишите их в names.txt и запустите скрипт ещё раз.",
                "# Слова, которые точно не имена, можно перенести в keep.txt, чтобы не мешали.",
                "# количество\tслово\tпример"]
        rows += [f"{c}\t{w}\t{suggest_example[w]}" for w, c in suggest.most_common()]
        Path(args.suggest).write_text("\n".join(rows) + "\n", encoding="utf-8")

    if args.audit:
        rows = []
        for cat, mp in vault.maps.items():
            for _, ph in mp.items():
                for orig in sorted(vault.originals[ph]):
                    rows.append(f"{ph}\t{orig}")
        Path(args.audit).write_text("\n".join(sorted(rows)) + "\n", encoding="utf-8")

    print(f"Готово: {out_path}", file=sys.stderr)
    print(f"Сообщений сохранено: {len(out_msgs)} (из них пересланных: "
          f"{sum(1 for r in out_msgs if r.get('forwarded'))}); пропущено: "
          + (", ".join(f"{k} — {v}" for k, v in skipped.items()) or "0"), file=sys.stderr)
    if vault.hits:
        print("Замены: " + ", ".join(f"{k} — {v} (уникальных {len(vault.maps[k])})"
                                     for k, v in vault.hits.most_common()), file=sys.stderr)


if __name__ == "__main__":
    main()
