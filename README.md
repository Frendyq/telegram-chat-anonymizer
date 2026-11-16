# Telegram Chat Anonymizer

[Русский](README.ru.md) | **English**

[![Tests](https://github.com/Frendyq/telegram-chat-anonymizer/actions/workflows/tests.yml/badge.svg)](https://github.com/Frendyq/telegram-chat-anonymizer/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/Frendyq/telegram-chat-anonymizer)](https://github.com/Frendyq/telegram-chat-anonymizer/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Removes personal data from a Telegram Desktop chat export (`result.json`): names, phone numbers, emails, passwords, addresses and more. The result can be safely handed to an AI model for analysis, to a researcher or to a colleague.

It runs **fully offline**: nothing is sent anywhere, and no libraries need to be installed. You only need Python, or the ready-made Windows program.

The tool is built for chats in **Russian and Kazakh**, but it also handles English names, phone numbers, emails, links and secrets in any language. The program messages and the replacement tags are in Russian. The [tag glossary](#tag-glossary) below lists them in English.

---

## What you get

Before:
```
Мария Иванова: Привет, Алексей Петрович! Мой номер +7 (700) 123-45-67,
               почта maria@example.com, живу на ул. Ленина 15, кв 42
```
After:
```
Человек А: Привет, [Человек Б]! Мой номер [ТЕЛЕФОН_1],
           почта [ПОЧТА_1], живу на [АДРЕС_1]
```
*(«Человек А» means "Person A"; the line reads: "Hi, [Person B]! My number is [PHONE_1], email [EMAIL_1], I live at [ADDRESS_1]".)*

Identical values always get identical tags. That way you can see that `[ИМЯ_3]` in different messages is the same person, and the conversation still makes sense.

## What gets hidden

| What | Example | Tag |
|---|---|---|
| Message authors | Мария Иванова | `Человек А` / `Человек Б` |
| Names in the text: all grammatical cases, diminutives, lowercase, Latin spelling, stretched spelling | Ерлану, Лёха, айгерим, Ерлааан, John | `[ИМЯ_n]` |
| Surnames and patronymics next to a name, Kazakh full names | Алексей Петрович, Серікұлы Нұрлан | `[ИМЯ_n]` |
| Phone numbers in any format | +7 (700) 123-45-67, 87001234567 | `[ТЕЛЕФОН_n]` |
| Emails | name@example.com | `[ПОЧТА_n]` |
| Card numbers (with Luhn check), Kazakh IIN, other long numbers | 4111 1111 1111 1111 | `[КАРТА_n]`, `[ИИН_n]`, `[НОМЕР_n]` |
| Links, domains, @usernames, t.me/… | t.me/channel, @nickname | `[ССЫЛКА_n]`, `[ДОМЕН_n]`, `[НИК_n]` |
| Passwords, tokens, API keys | password: Summer2024!, sk-…, DB_PASSWORD=… | `[ПАРОЛЬ_n]`, `[СЕКРЕТ_n]` |
| Addresses | ул. Ленина 15, кв 42; мкр Восток-5, д. 8 | `[АДРЕС_n]` |
| ID documents and licence plates | passport N12345678; 777ABC02 | `[ДОКУМЕНТ_n]`, `[ГОСНОМЕР_n]` |
| GPS coordinates, `C:\Users\name` paths | 43.2389, 76.8897 | `[КООРДИНАТЫ_n]`, `[НИК_n]` |
| Your own words from `hide.txt`: city, university, employer | Караганда, Каспий банк | `[СКРЫТО_n]` |

The tool also removes user IDs, usernames, file names, reactions and service events from the file. Forwarded messages are kept, and the original sender is replaced with `[ЧЕЛОВЕК_n]`. Only messages from the two chat participants remain.

The built-in dictionary (`builtin_names.txt`) contains about 1,300 names:
- Russian and Ukrainian;
- Kazakh;
- Uzbek, Kyrgyz and Tajik;
- Tatar and Caucasian;
- English;
- foreign names written in Cyrillic.

### Tag glossary

| Tag | Meaning |
|---|---|
| `Человек А`, `Человек Б` | Person A, Person B (the two chat participants) |
| `[ИМЯ_n]` | name |
| `[ЧЕЛОВЕК_n]` | original sender of a forwarded message |
| `[ТЕЛЕФОН_n]` | phone number |
| `[ПОЧТА_n]` | email |
| `[КАРТА_n]` | bank card number |
| `[ИИН_n]` | Kazakh individual ID number (IIN) |
| `[НОМЕР_n]` | other long number |
| `[ССЫЛКА_n]` | link (URL) |
| `[ДОМЕН_n]` | domain name |
| `[НИК_n]` | username / login |
| `[ПАРОЛЬ_n]` | password |
| `[СЕКРЕТ_n]` | token, API key or other secret |
| `[ИД_n]` | technical identifier (UUID, project ID) |
| `[АДРЕС_n]` | street address |
| `[КООРДИНАТЫ_n]` | GPS coordinates |
| `[ДОКУМЕНТ_n]` | passport / ID card / contract number |
| `[ГОСНОМЕР_n]` | vehicle licence plate |
| `[СКРЫТО_n]` | word from your `hide.txt` |

---

## Quick start

### 1. Export the chat from Telegram

1. Open **Telegram Desktop**. The mobile apps cannot export chats.
2. Open the chat and click **⋮ → Export chat history**.
3. Untick photos, videos and files: only text is needed.
4. At the bottom, choose the format **Machine-readable JSON**.
5. Click **Export**. You will get a `ChatExport_…` folder with a `result.json` file.

### 2a. Windows: ready-made program, no Python needed

1. Download **`TelegramAnonymizer.exe`** from [Releases](https://github.com/Frendyq/telegram-chat-anonymizer/releases/latest).
2. Run it and pick `result.json`. You can also drag `result.json`, or the whole `ChatExport_…` folder, onto the program.
3. The program anonymizes the chat and immediately checks the result for leaks.

> Windows may show **"Windows protected your PC"** because the program has no paid code-signing certificate. Click **More info → Run anyway**. The program works offline, and its source code is open in this repository. If you'd rather not trust a prebuilt `.exe`, build it yourself with `build_exe.bat`.

Put your own lists (`names.txt`, `hide.txt`, `keep.txt`, see below) **next to `TelegramAnonymizer.exe`**.

### 2b. Any OS: Python script

1. Install Python 3.9 or newer from [python.org](https://www.python.org/downloads/). On Windows, tick **Add Python to PATH** during installation.
2. Download the script: **Code → Download ZIP** on this page, or with git:
   ```bash
   git clone https://github.com/Frendyq/telegram-chat-anonymizer.git
   ```
3. Run it. On Windows, the easiest way is to drag `result.json` onto `run.bat`. From a terminal:
   ```bash
   python anonymize_tg.py path/to/result.json --txt anon.txt --suggest suggest.txt
   ```

`result_anon.json`, the anonymized chat, will appear next to `result.json`.

---

## Getting a clean result

Phone numbers, emails, cards and passwords are recognised by their format, almost without misses. **Names are harder:** a rare name that is not in the dictionary may slip through. So it's best to go through this loop.

**1. List the names you know.** Copy `names.example.txt` to `names.txt` and list the people mentioned in the chat: friends, relatives, colleagues, their nicknames and surnames.
```
Алексей, Лёша, Лёха, Смирнов
Айгерим, Айка
```
One line is one person; variants go comma-separated. You don't need to write grammatical cases, lowercase or Latin spellings: the tool generates them.

**2. Hide places.** Copy `hide.example.txt` to `hide.txt` and list your city, street, university, employer: anything that could identify you. For single words of five letters or more, every word starting with them is hidden too (`Караганда` also hides `в Караганде` and `карагандинский`). For phrases, the cases of the last word are hidden too.

**3. Run with `--suggest`.** `suggest.txt` lists capitalised words that are still in the text and do not start a sentence. Look through it and add any names you find to `names.txt`.

**4. If the tool hides too much** (for example, it treats the voice assistant «Алиса» as a person), add that word to `keep.txt`.

**5. Run again and check the result:**
```bash
python check_anon.py path/to/result_anon.json
```
The checker uses its own, independent rules to look for leftover phone numbers, emails, cards, links, passwords, addresses, documents and names from `names.txt`. **It prints only counts, never the chat text.** If every line says `OK`, the file is clean. With `--show` it also prints the matched words, still without the surrounding text.

> **Warning:** `names.txt`, `hide.txt` and `keep.txt` contain your personal data. Don't publish them. They are already listed in `.gitignore`.

---

## Options

```
python anonymize_tg.py result.json [options]

  -o, --output FILE      where to save the JSON (default: result_anon.json next to the input)
  --txt FILE             also save the chat as plain text
  --suggest FILE         list of words that may be missed names
  --names / --hide / --keep FILE
                         your own lists (default: names.txt / hide.txt / keep.txt next to the script)
  --a, --b NAME          who is "Person A" and "Person B"
                         (default: the two most active participants)
  --label-a, --label-b   your own labels instead of «Человек А» / «Человек Б»,
                         e.g. --label-a "Person A" --label-b "Person B"
  --no-dates             remove message dates
  --audit FILE           table "original value → tag" for review.
                         Warning: it contains all the original data, never share it
  --no-ner               don't use natasha even if it is installed
```

The Windows program accepts the same options after the file path:
```
TelegramAnonymizer.exe result.json --no-dates --label-a "Person A" --label-b "Person B"
```

**Optional:** if [natasha](https://github.com/natasha/natasha) is installed (`pip install natasha`), Russian names are additionally detected by a neural model. It's slower, but catches rare names.

## Output format

The structure mirrors the Telegram export, so the same tools can read it:
```json
{
 "name": "Анонимный чат",
 "participants": ["Человек А", "Человек Б"],
 "messages": [
  {"id": 1, "type": "message", "date": "2026-01-10T09:01:00",
   "from": "Человек А", "from_id": "A", "text": "Привет, [Человек Б]! …"},
  {"id": 2, "from": "Человек Б", "reply_to_message_id": 1, "forwarded": true,
   "forwarded_from": "[ЧЕЛОВЕК_1]", "media": "фото", "text": "…"}
 ]
}
```
`media` describes attachments in Russian: `фото` (photo), `файл` (file), `видео` (video), `голосовое сообщение` (voice message), `стикер` (sticker) and so on.

## Limitations

- **A rare name that is in neither the dictionary nor `names.txt`, and is always written in lowercase,** will not be found. If it is capitalised, it will show up in `suggest.txt`.
- **Names that are also common words** («Роза», «Вера», «Лев», «мина», «марка»; English Will, Grace, Ruby) are deliberately not hidden, or hidden only when capitalised. If they are names in your chat, add them to `names.txt`.
- **A password that is a single dictionary word with no hint** (just "qwerty" on its own) cannot be told apart from an ordinary word.
- **Indirect details** (events, profession, studies, appearance) are left alone. People who know you may still recognise someone from them. If that matters, read through the result and add words to `hide.txt`.
- **Only a single-chat export in JSON format is supported.** The HTML format and full account exports are not.
- **Grammatical forms are generated for Russian and Kazakh.** Names in other languages are matched only in their exact form.
- **Usernames like `john_smith99` are hidden only when they contain a name from `names.txt`** (or a name of five letters or more that appears capitalised in the chat). Add such people to `names.txt`, or hide the username with `hide.txt`.

## Tests and releases

```bash
python -m unittest discover -s tests
```

Tests run automatically on GitHub for every change: Windows, Linux and macOS, Python 3.9–3.14.

To release a new version of the program, just push a tag:
```bash
git tag v1.1.0
git push origin v1.1.0
```
GitHub then builds `TelegramAnonymizer.exe`, smoke-tests it on the sample chat and publishes it to [Releases](https://github.com/Frendyq/telegram-chat-anonymizer/releases).

## License

[MIT](LICENSE): free to use, modify and distribute.
