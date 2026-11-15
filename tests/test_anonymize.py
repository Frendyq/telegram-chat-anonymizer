"""Тесты: python -m unittest discover -s tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import anonymize_tg as A  # noqa: E402


def make_anonymizer(people=(), hide=(), keep=()):
    names = A.NameIndex()
    names.keep = {A.norm(k) for k in keep}
    for p in people:
        names.add_person(list(p))
    for n in A.load_builtin_names():
        names.add_dict_name(n)
    names.finalize()
    return A.Anonymizer(A.Vault(), names, list(hide), {}, use_ner=False)


class TestContacts(unittest.TestCase):
    def setUp(self):
        self.a = make_anonymizer()

    def check_hidden(self, text, secret):
        out = self.a.redact(text)
        self.assertNotIn(secret, out, out)
        return out

    def test_phones(self):
        for t, s in [("звони +7 (700) 123-45-67", "123-45-67"), ("номер 87001234567", "87001234567"),
                     ("8 777 123 45 67", "123 45 67")]:
            self.assertIn("[ТЕЛЕФОН_", self.check_hidden(t, s))

    def test_email_card_iin(self):
        self.assertIn("[ПОЧТА_", self.check_hidden("пиши a.b@example.com", "a.b@example.com"))
        self.assertIn("[КАРТА_", self.check_hidden("карта 4111 1111 1111 1111", "4111 1111"))
        self.check_hidden("ИИН 990101300123", "990101300123")

    def test_links_and_nicks(self):
        self.check_hidden("канал t.me/some_channel", "some_channel")
        self.check_hidden("сайт https://example.org/page?id=5", "example.org")
        self.check_hidden("пиши @petr_sidorov_99", "petr_sidorov_99")

    def test_secrets(self):
        self.check_hidden("пароль: Summer2024!", "Summer2024!")
        self.check_hidden("DB_PASSWORD=S3cr3t!pass", "S3cr3t!pass")
        self.check_hidden("token sk-ant-abcdefghijklmnopqrstuvwxyz123456", "abcdefghijklmnop")
        self.check_hidden("a@example.com\nQwerty_2024", "Qwerty_2024")

    def test_addresses_and_documents(self):
        self.assertIn("[АДРЕС_", self.check_hidden("живём на ул. Ленина 15, кв 42", "Ленина 15"))
        self.check_hidden("мкр Восток-5, д. 8", "Восток-5")
        self.check_hidden("паспорт N12345678", "N12345678")
        self.check_hidden("координаты 43.238949, 76.889709", "43.238949")


class TestNames(unittest.TestCase):
    def test_builtin_names_any_case(self):
        a = make_anonymizer()
        out = a.redact("Ерлан пришёл, а маша и айгерим опоздали. Передай Ерлану привет")
        for w in ("Ерлан", "маша", "айгерим", "Ерлану"):
            self.assertNotIn(w, out, out)

    def test_surname_and_patronymic(self):
        out = make_anonymizer().redact("Привет, Алексей Петрович! Серікұлы Нұрлан тоже тут")
        self.assertNotIn("Петрович", out)
        self.assertNotIn("Серікұлы", out)

    def test_user_names_forms_and_nicks(self):
        a = make_anonymizer(people=[("Камшат", "Камша")])
        out = a.redact("камшатка и Камше передай, ник kamshat_2005")
        self.assertNotIn("камшат", out.lower(), out)
        self.assertNotIn("Камше", out)

    def test_stretched_and_kazakh_letters(self):
        out = make_anonymizer().redact("Ерлааан, Нұрлан и Нурлан")
        self.assertNotIn("Ерлааан", out)
        self.assertNotIn("Нұрлан", out)
        self.assertNotIn("Нурлан", out)

    def test_common_words_untouched(self):
        a = make_anonymizer()
        for t in ["на улице холодно", "площадь 50 кв м", "что за марка?", "крыша мира",
                  "любой человек", "новая майка", "ты права", "ноу проблем", "надо идти",
                  "Версия 2.1, 14:30, 100 USD", "в Караганде тепло"]:
            self.assertEqual(a.redact(t), t)

    def test_keep_list(self):
        out = make_anonymizer(keep=["Алиса"]).redact("помощник Алиса ответил")
        self.assertIn("Алиса", out)

    def test_hide_list(self):
        out = make_anonymizer(hide=["Караганда", "Каспий банк"]).redact(
            "живу в Караганде, карагандинский, работаю в каспий банке")
        self.assertNotIn("Караганд", out)
        self.assertNotIn("карагандин", out)
        self.assertNotIn("каспий", out.lower())


class TestEndToEnd(unittest.TestCase):
    def test_sample_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.txt"
            empty.write_text("", encoding="utf-8")
            out = Path(tmp) / "out.json"
            r = subprocess.run(
                [sys.executable, str(ROOT / "anonymize_tg.py"), str(ROOT / "examples" / "sample_chat.json"),
                 "-o", str(out), "--names", str(ROOT / "names.example.txt"),
                 "--hide", str(ROOT / "hide.example.txt"), "--keep", str(empty), "--no-ner"],
                capture_output=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
            text = out.read_text(encoding="utf-8")
            for secret in ["Смирнов", "Иванова", "123-45-67", "alexey.smirnov", "4111", "Ерлан",
                           "Айгерим", "Касымов", "Summer2024", "Ленина", "petr_sidorov", "Пётр",
                           "Сидоров", "990101300123", "user1000000", "ерлан", "машей"]:
                self.assertNotIn(secret, text, secret)
            self.assertEqual({m["from"] for m in data["messages"]}, {"Человек А", "Человек Б"})
            self.assertTrue(any(m.get("forwarded") for m in data["messages"]))
            self.assertIn("на улице холодно", text)

            r = subprocess.run([sys.executable, str(ROOT / "check_anon.py"), str(out),
                                "--names", str(ROOT / "names.example.txt")],
                               capture_output=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("!!", r.stdout, r.stdout)


if __name__ == "__main__":
    unittest.main()
