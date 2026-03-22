"""
Tests fuer isolierte Brain-Funktionen:
  - _detect_sarcasm_feedback: Sarkasmus-Reaktionserkennung
  - _detect_problem_solving_intent: Problemloesungs-Intent
  - _detect_smalltalk: Smalltalk/Identitaets-Shortcuts
  - _detect_calendar_diagnostic: Kalender-Diagnose
  - _DAS_UEBLICHE_PATTERNS: "Das Uebliche"-Erkennung
  - Response-Filter: Refusals, Chatbot-Floskeln, Markdown, Safety
"""

import re
import pytest


# ============================================================
# Sarkasmus-Feedback-Erkennung
# ============================================================

_SARCASM_POSITIVE = frozenset(
    [
        "haha",
        "lol",
        "hehe",
        "hihi",
        "xd",
        "witzig",
        "lustig",
        "gut",
        "stimmt",
        "genau",
        "ja",
        "ok",
        "passt",
        "nice",
        "geil",
        "👍",
        "😂",
        "😄",
        "🤣",
    ]
)

_SARCASM_NEGATIVE = frozenset(
    [
        "hoer auf",
        "lass das",
        "sei ernst",
        "nicht witzig",
        "nervt",
        "ernst",
        "bitte sachlich",
        "ohne sarkasmus",
        "ohne witz",
        "lass den quatsch",
        "reicht",
        "genug",
    ]
)


def detect_sarcasm_feedback(text: str) -> bool | None:
    """Kopie aus brain.py fuer isoliertes Testen.

    FIX: Negative Patterns werden ZUERST geprueft, damit "nicht witzig"
    nicht faelschlich als positiv erkannt wird (weil "witzig" in positives).
    FIX: Word-Boundaries fuer kurze positive Patterns (<=3 Zeichen),
    damit "gut" nicht "guten morgen" matcht.
    """
    text_lower = text.lower().strip()
    words = text_lower.split()
    # Negative ZUERST — "nicht witzig" muss negativ sein, nicht positiv
    if any(p in text_lower for p in _SARCASM_NEGATIVE):
        return False
    # Kurze positive Reaktionen (1-3 Woerter)
    if len(words) <= 3:
        for p in _SARCASM_POSITIVE:
            if len(p) <= 3 and p.isascii() and p.isalpha():
                if re.search(r"\b" + re.escape(p) + r"\b", text_lower):
                    return True
            elif p in text_lower:
                return True
    return None


class TestSarcasmFeedback:
    """Erkennt positive/negative Reaktionen auf Sarkasmus."""

    @pytest.mark.parametrize(
        "text",
        [
            "haha",
            "lol",
            "witzig",
            "nice",
            "geil",
            "😂",
            "ok passt",
            "ja genau",
            "gut so",
        ],
    )
    def test_positive_feedback(self, text):
        assert detect_sarcasm_feedback(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "hoer auf damit",
            "lass das bitte",
            "sei ernst",
            "nervt mich",
            "bitte sachlich",
            "ohne sarkasmus bitte",
            "reicht jetzt",
            "nicht witzig",  # Regression: war vorher positiv wegen "witzig"
        ],
    )
    def test_negative_feedback(self, text):
        assert detect_sarcasm_feedback(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            "wie ist das wetter",
            "mach das licht an",
            "ich bin muede",
            "guten morgen",  # Regression: "gut" matchte "guten" als Substring
        ],
    )
    def test_neutral_no_feedback(self, text):
        assert detect_sarcasm_feedback(text) is None

    def test_positive_too_long(self):
        """Positive Patterns greifen nur bei <=3 Woertern."""
        result = detect_sarcasm_feedback("das war ja wirklich witzig und lustig")
        # >3 Woerter → positive Patterns greifen nicht
        # Aber "lustig" und "witzig" sind auch nicht in _SARCASM_NEGATIVE
        assert result is None

    def test_negative_any_length(self):
        """Negative Patterns greifen bei beliebiger Laenge."""
        result = detect_sarcasm_feedback(
            "Also bitte sei jetzt mal ernst und hoer auf damit"
        )
        assert result is False

    # Regression: Bug wo negative Prüfung NACH positiver lief
    def test_regression_nicht_witzig_is_negative(self):
        """'nicht witzig' muss negativ sein, nicht positiv (wegen 'witzig')."""
        assert detect_sarcasm_feedback("nicht witzig") is False

    def test_regression_guten_morgen_is_neutral(self):
        """'guten morgen' darf nicht positiv sein (wegen 'gut' Substring)."""
        assert detect_sarcasm_feedback("guten morgen") is None

    def test_gut_alone_is_positive(self):
        """'gut' allein (als ganzes Wort) ist positiv."""
        assert detect_sarcasm_feedback("gut") is True

    def test_ja_alone_is_positive(self):
        """'ja' allein ist positiv (Word-Boundary Match)."""
        assert detect_sarcasm_feedback("ja") is True

    def test_ok_alone_is_positive(self):
        """'ok' allein ist positiv (Word-Boundary Match)."""
        assert detect_sarcasm_feedback("ok") is True


# ============================================================
# Problem-Solving-Intent
# ============================================================

_PROBLEM_PATTERNS = frozenset(
    [
        "wie kann ich",
        "ich brauche",
        "zu warm",
        "zu kalt",
        "zu dunkel",
        "zu hell",
        "strom sparen",
        "energie sparen",
        "hast du eine idee",
        "was schlaegst du vor",
        "was wuerdest du",
        "loesung",
        "problem",
        "wie kriege ich",
        "was tun",
        "vorschlag",
        "tipp",
        "empfehlung",
        "wie spare ich",
        "wie reduziere ich",
        "zu laut",
        "zu leise",
        "hilf mir",
        "was mache ich",
        "alternative",
        "wie geht das",
        "geht das besser",
        "optimieren",
        "verbessern",
        "was empfiehlst du",
        "kannst du helfen",
    ]
)


def detect_problem_solving_intent(text: str) -> bool:
    text_lower = text.lower().strip()
    return any(p in text_lower for p in _PROBLEM_PATTERNS)


class TestProblemSolvingIntent:
    """Erkennt ob der User ein Problem beschreibt."""

    @pytest.mark.parametrize(
        "text",
        [
            "Es ist zu warm im Wohnzimmer",
            "Wie kann ich Strom sparen?",
            "Ich brauche Hilfe mit der Heizung",
            "Hast du eine Idee?",
            "Hilf mir bitte",
            "Was wuerdest du vorschlagen?",
            "Gibt es eine Alternative?",
            "Wie spare ich Energie?",
            "Das geht das besser",
            "Kannst du helfen?",
        ],
    )
    def test_problem_detected(self, text):
        assert detect_problem_solving_intent(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Licht an",
            "Wie warm ist es?",
            "Guten Morgen",
            "Danke nichts davon",
            "Hallo Jarvis",
            "Musik abspielen",
            "Rollladen hoch",
        ],
    )
    def test_no_problem_detected(self, text):
        assert detect_problem_solving_intent(text) is False, (
            f"'{text}' sollte KEIN Problem-Solving-Intent sein"
        )

    def test_danke_nichts_davon_regression(self):
        """Regression: 'Danke nichts davon' hat faelschlicherweise 5 upgrade_signals ausgeloest."""
        assert detect_problem_solving_intent("Danke nichts davon") is False


# ============================================================
# Smalltalk-Erkennung
# ============================================================


class TestSmallTalkDetection:
    """Testet _detect_smalltalk Patterns isoliert."""

    # Wake-Word-Erkennung
    @pytest.mark.parametrize(
        "text,expected_prefix_removed",
        [
            ("Hey Jarvis", None),  # Nur Wake-Word → Begruessung (nicht None)
            ("Hallo Jarvis", None),
            ("Jarvis", None),
        ],
    )
    def test_wake_word_only_returns_greeting(self, text, expected_prefix_removed):
        """Nur Wake-Word ohne Frage → Kurze Begruessung."""
        # Simuliere die Wake-Word-Logik
        t = text.lower().strip().rstrip("?!.")
        _wake_prefixes = [
            "hey jarvis",
            "hallo jarvis",
            "hi jarvis",
            "ok jarvis",
            "jarvis",
        ]
        greeting_returned = False
        for _wp in _wake_prefixes:
            if t.startswith(_wp):
                rest = t[len(_wp) :].strip().lstrip(",").strip()
                if not rest:
                    greeting_returned = True
                break
        assert greeting_returned is True

    def test_wake_word_with_question_continues(self):
        """Wake-Word + Frage → Frage wird weiterverarbeitet."""
        t = "hey jarvis wer bist du".lower().strip()
        _wake_prefixes = [
            "hey jarvis",
            "hallo jarvis",
            "hi jarvis",
            "ok jarvis",
            "jarvis",
        ]
        rest = None
        for _wp in _wake_prefixes:
            if t.startswith(_wp):
                rest = t[len(_wp) :].strip().lstrip(",").strip()
                break
        assert rest == "wer bist du"

    # Identitaetsfragen
    @pytest.mark.parametrize(
        "text",
        [
            "Wer bist du?",
            "Was bist du?",
            "Wie heisst du?",
            "Bist du ein Mensch?",
            "Bist du eine KI?",
            "Bist du ein Roboter?",
            "Bist du echt?",
        ],
    )
    def test_identity_questions_detected(self, text):
        t = text.lower().strip().rstrip("?!.")
        _identity = [
            "wer bist du",
            "was bist du",
            "wie heisst du",
            "wie heißt du",
            "bist du ein mensch",
            "bist du eine ki",
            "bist du ein roboter",
            "bist du echt",
        ]
        assert any(kw in t for kw in _identity)

    # "Kennst du mich?" Fragen
    @pytest.mark.parametrize(
        "text",
        [
            "Weisst du wer ich bin?",
            "Kennst du mich?",
            "Wer bin ich?",
            "Wie heisse ich?",
        ],
    )
    def test_know_me_questions_detected(self, text):
        t = text.lower().strip().rstrip("?!.")
        _know_me = [
            "weisst du wer ich bin",
            "weißt du wer ich bin",
            "kennst du mich",
            "wer bin ich",
            "weisst du meinen namen",
            "weißt du meinen namen",
            "wie heisse ich",
            "wie heiße ich",
        ]
        assert any(kw in t for kw in _know_me)

    # Danke-Patterns
    @pytest.mark.parametrize(
        "text",
        [
            "Danke Jarvis",
            "Danke dir",
            "Danke schoen",
            "Vielen Dank",
            "Dankeschoen",
            "Danke",
        ],
    )
    def test_thanks_detected(self, text):
        t = text.lower().strip().rstrip("?!.")
        _thanks = [
            "danke jarvis",
            "danke dir",
            "danke schoen",
            "danke sehr",
            "vielen dank",
            "dankeschoen",
            "dankeschön",
            "danke schön",
        ]
        is_thanks = any(kw in t for kw in _thanks) or t.strip().rstrip("!.") == "danke"
        assert is_thanks is True

    # Nicht als Smalltalk erkannt
    @pytest.mark.parametrize(
        "text",
        [
            "Wie geht es dir?",
            "Guten Morgen",
            "Was machst du gerade?",
            "Erzaehl mir einen Witz",
            "Mach das Licht an",
        ],
    )
    def test_not_smalltalk_goes_to_llm(self, text):
        """Diese Saetze sollen ans LLM durchgelassen werden."""
        t = text.lower().strip().rstrip("?!.")

        _identity = [
            "wer bist du",
            "was bist du",
            "wie heisst du",
            "wie heißt du",
            "bist du ein mensch",
            "bist du eine ki",
            "bist du ein roboter",
            "bist du echt",
        ]
        _know_me = [
            "weisst du wer ich bin",
            "weißt du wer ich bin",
            "kennst du mich",
            "wer bin ich",
        ]
        _thanks = [
            "danke jarvis",
            "danke dir",
            "danke schoen",
            "danke sehr",
            "vielen dank",
            "dankeschoen",
            "dankeschön",
        ]

        is_identity = any(kw in t for kw in _identity)
        is_know_me = any(kw in t for kw in _know_me)
        is_thanks = any(kw in t for kw in _thanks) or t == "danke"

        assert not (is_identity or is_know_me or is_thanks), (
            f"'{text}' sollte ans LLM weitergeleitet werden"
        )


# ============================================================
# Kalender-Diagnose
# ============================================================


class TestCalendarDiagnostic:
    """Erkennt Fragen nach verfuegbaren Kalendern."""

    @staticmethod
    def _detect(text: str) -> bool:
        t = text.lower().strip()
        return any(
            kw in t
            for kw in [
                "welchen kalender",
                "welche kalender",
                "welcher kalender",
                "kalender hast du",
                "kalender siehst du",
                "kalender nutzt du",
                "kalender verwendest du",
                "kalender gibt es",
                "zeig mir die kalender",
                "zeig kalender entities",
                "kalender konfigur",
            ]
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Welche Kalender hast du?",
            "Welchen Kalender nutzt du?",
            "Zeig mir die Kalender",
            "Kalender konfigurieren",
        ],
    )
    def test_calendar_diagnostic_detected(self, text):
        assert self._detect(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Was steht morgen im Kalender?",
            "Habe ich heute Termine?",
            "Wann ist der naechste Termin?",
        ],
    )
    def test_not_calendar_diagnostic(self, text):
        assert self._detect(text) is False


# ============================================================
# "Das Uebliche" Patterns
# ============================================================


class TestDasUebliche:
    """Erkennt 'Das Uebliche' / 'Wie immer' Patterns."""

    _PATTERNS = [
        "das uebliche",
        "das übliche",
        "wie immer",
        "mach fertig",
        "mach alles fertig",
        "wie gewohnt",
        "das gleiche wie immer",
        "du weisst schon",
        "mach mal",
        "mach das ding",
    ]

    def _detect(self, text: str) -> bool:
        text_lower = text.lower().strip()
        return any(p in text_lower for p in self._PATTERNS)

    @pytest.mark.parametrize(
        "text",
        [
            "Das Uebliche bitte",
            "Mach wie immer",
            "Mach fertig",
            "Wie gewohnt bitte",
            "Du weisst schon",
            "Mach mal",
        ],
    )
    def test_das_uebliche_detected(self, text):
        assert self._detect(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Mach das Licht an",
            "Wie geht es dir?",
            "Was gibt es Neues?",
        ],
    )
    def test_not_das_uebliche(self, text):
        assert self._detect(text) is False


# ============================================================
# Response-Filter: Refusal-Patterns
# ============================================================


class TestRefusalRemoval:
    """LLM-Refusals werden aus Antworten entfernt."""

    _REFUSAL_PATTERNS = [
        r"[Aa]ber ich kann diese Anfrage nicht erf[uü]llen\.?",
        r"[Ii]ch kann diese Anfrage nicht erf[uü]llen\.?",
        r"[Ii]ch kann dir dabei (?:leider )?nicht helfen\.?",
        r"[Dd]as kann ich (?:leider )?nicht (?:tun|machen|beantworten|erf[uü]llen)\.?",
        r"[Ii]ch bin nicht in der Lage,? (?:das|dies|diese Anfrage).*?(?:\.|!|$)",
        r"[Dd]iese Anfrage kann ich (?:leider )?nicht.*?(?:\.|!|$)",
        r"[Ii]ch habe (?:leider )?keinen Zugriff.*?(?:\.|!|$)",
        r"[Ii]ch habe (?:leider )?keine M[oö]glichkeit.*?(?:\.|!|$)",
    ]

    def _remove_refusals(self, text: str) -> str:
        for rp in self._REFUSAL_PATTERNS:
            text = re.sub(rp, "", text, flags=re.IGNORECASE).strip()
        return text

    @pytest.mark.parametrize(
        "input_text,expected_clean",
        [
            (
                "Aber ich kann diese Anfrage nicht erfüllen. Hier ist die Temperatur.",
                "Hier ist die Temperatur.",
            ),
            ("Ich kann dir dabei nicht helfen. Das Licht ist an.", "Das Licht ist an."),
            ("Das kann ich leider nicht tun. Versuch es anders.", "Versuch es anders."),
            ("Ich habe leider keinen Zugriff auf die Daten.", ""),
            ("Ich habe keine Möglichkeit das zu ändern.", ""),
        ],
    )
    def test_refusals_removed(self, input_text, expected_clean):
        result = self._remove_refusals(input_text)
        assert result == expected_clean

    def test_no_refusal_unchanged(self):
        text = "Die Temperatur betraegt 22 Grad."
        assert self._remove_refusals(text) == text


# ============================================================
# Response-Filter: Chatbot-Floskeln
# ============================================================


class TestChatbotPhrases:
    """Chatbot-Floskeln werden entfernt."""

    _CHATBOT_FLOSKELS = [
        r"Wenn (?:du|Sie) (?:noch |weitere )?Fragen ha(?:ben|st).*?(?:\.|!|$)",
        r"(?:Ich )?[Ss]tehe? (?:dir|Ihnen) (?:gerne |jederzeit )?zur Verf[uü]gung.*?(?:\.|!|$)",
        r"Zögern? (?:du|Sie) nicht.*?(?:\.|!|$)",
        r"(?:Ich bin )?(?:hier,? )?um (?:dir|Ihnen) zu helfen.*?(?:\.|!|$)",
        r"Lass(?:e|t)? (?:es )?mich wissen.*?(?:\.|!|$)",
    ]

    def _remove_chatbot(self, text: str) -> str:
        for floskel in self._CHATBOT_FLOSKELS:
            text = re.sub(floskel, "", text, flags=re.IGNORECASE).strip()
        return text

    @pytest.mark.parametrize(
        "input_text",
        [
            "Erledigt. Wenn du noch Fragen hast, sag Bescheid.",
            "Alles klar. Ich stehe dir gerne zur Verfügung.",
            "Das Licht ist an. Lass mich wissen wenn du mehr brauchst.",
            "22 Grad. Ich bin hier um dir zu helfen.",
        ],
    )
    def test_chatbot_floskeln_removed(self, input_text):
        result = self._remove_chatbot(input_text)
        assert "Fragen" not in result or "Fragen ha" not in result
        # Hauptinhalt bleibt erhalten
        assert len(result) > 0 or "Erledigt" in input_text


# ============================================================
# Response-Filter: Markdown-Entfernung
# ============================================================


class TestMarkdownRemoval:
    """Markdown-Formatierung wird entfernt."""

    def _remove_markdown(self, text: str) -> str:
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        text = re.sub(r"^[\-\*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"`(.+?)`", r"\1", text)
        return text

    def test_headers_removed(self):
        assert self._remove_markdown("### Temperatur") == "Temperatur"
        assert self._remove_markdown("# Ueberschrift") == "Ueberschrift"

    def test_bold_removed(self):
        assert self._remove_markdown("Das ist **wichtig**") == "Das ist wichtig"

    def test_italic_removed(self):
        assert self._remove_markdown("Das ist *kursiv*") == "Das ist kursiv"

    def test_bullets_removed(self):
        assert (
            self._remove_markdown("- Punkt eins\n- Punkt zwei")
            == "Punkt eins\nPunkt zwei"
        )

    def test_numbered_list_removed(self):
        assert self._remove_markdown("1. Erster\n2. Zweiter") == "Erster\nZweiter"

    def test_code_backticks_removed(self):
        assert self._remove_markdown("Nutze `set_light`") == "Nutze set_light"

    def test_no_markdown_unchanged(self):
        text = "Das Licht ist an."
        assert self._remove_markdown(text) == text


# ============================================================
# Response-Filter: Safety (Sicherheitsgeraete)
# ============================================================


class TestSafetyFilter:
    """Sicherheitsgeraete duerfen nie als ignorierbar dargestellt werden."""

    _safety_devices = r"(?:rauchmelder|co[2-]?[\s-]?melder|kohlenmonoxid|gasmelder|wassermelder|alarmsystem|alarmanlage|brandmelder)"

    _dismiss_patterns = None

    @pytest.fixture(autouse=True)
    def setup_patterns(self):
        sd = self._safety_devices
        self._dismiss_patterns = [
            re.compile(
                rf"{sd}\s+(?:ignorier|vernachlaessig|uebergeh|weglass|ausblend)",
                re.IGNORECASE,
            ),
            re.compile(
                rf"(?:ignorier|vernachlaessig|uebergeh|vergiss)\w*\s+(?:den|die|das)\s+{sd}",
                re.IGNORECASE,
            ),
            re.compile(
                rf"{sd}\s+(?:ist\s+)?(?:unwichtig|harmlos|egal|kein\s+problem|nicht\s+(?:schlimm|wichtig|relevant))",
                re.IGNORECASE,
            ),
            re.compile(
                rf"kannst\s+(?:du\s+)?(?:den|die|das)\s+{sd}.*?ignorier", re.IGNORECASE
            ),
        ]

    def _is_safety_violation(self, text: str) -> bool:
        return any(p.search(text) for p in self._dismiss_patterns)

    @pytest.mark.parametrize(
        "text",
        [
            "Den Rauchmelder ignorieren wir einfach.",
            "Rauchmelder ist nicht wichtig.",
            "Vergiss den Rauchmelder.",
            "Rauchmelder ist harmlos.",
            "Kannst du den Rauchmelder ignorieren?",
            "CO2-Melder ist egal.",
            "Gasmelder vernachlaessigen.",
            "Alarmanlage ist kein Problem.",
        ],
    )
    def test_safety_violations_detected(self, text):
        assert self._is_safety_violation(text), (
            f"Safety-Violation nicht erkannt: '{text}'"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Der Rauchmelder ist aktiv.",
            "Rauchmelder zeigt keine Warnung.",
            "Alarmanlage ist scharf.",
            "CO2-Melder funktioniert einwandfrei.",
        ],
    )
    def test_safe_texts_pass(self, text):
        assert not self._is_safety_violation(text), f"Falscher Safety-Alarm: '{text}'"


# ============================================================
# Response-Filter: Exclamation Dampening
# ============================================================


class TestExclamationDampening:
    """Mehr als 2 Ausrufezeichen → nur das erste bleibt."""

    def _dampen(self, text: str) -> str:
        if text.count("!") > 2:
            _first_excl = text.index("!")
            text = text[: _first_excl + 1] + text[_first_excl + 1 :].replace("!", ".")
        text = re.sub(r"!{2,}", ".", text)
        return text

    def test_three_exclamations_dampened(self):
        text = "Super! Toll! Klasse! Wow!"
        result = self._dampen(text)
        assert result.count("!") == 1

    def test_two_exclamations_unchanged(self):
        text = "Super! Toll!"
        result = self._dampen(text)
        assert result.count("!") == 2

    def test_multiple_exclamation_marks(self):
        text = "Das ist toll!!!"
        result = self._dampen(text)
        assert "!!!" not in result

    def test_no_exclamation_unchanged(self):
        text = "Das Licht ist an."
        assert self._dampen(text) == text
