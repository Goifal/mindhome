"""
Tests fuer Sie→du Konversion in brain.py _filter_response()

Testet alle Regex-Patterns isoliert (ohne Brain-Instanz), da die
_filter_response-Methode viele Dependencies hat.

Regressionstests:
  - Variable-width lookbehind Crash: (?<=\\b\\w{3,}e\\s) → re.error
  - Imperativ-Catch-all: "praezisieren Sie" → "praezisiere"
  - Verb-Paare: "Haben Sie" → "Hast du"
  - Pronomen-Mapping: Ihnen→dir, Ihre→deine, etc.
"""

import re
import pytest


# ============================================================
# Hilfsfunktionen: Extrahiert aus brain.py _filter_response()
# ============================================================

def apply_verb_pairs(text: str) -> str:
    """Verb+Sie Paare ersetzen (aus brain.py)."""
    _verb_pairs = [
        (r"\bHaben Sie\b", "Hast du"), (r"\bhaben Sie\b", "hast du"),
        (r"\bKoennen Sie\b", "Kannst du"), (r"\bkoennen Sie\b", "kannst du"),
        (r"\bKönnen Sie\b", "Kannst du"), (r"\bkönnen Sie\b", "kannst du"),
        (r"\bMoechten Sie\b", "Moechtest du"), (r"\bmoechten Sie\b", "moechtest du"),
        (r"\bMöchten Sie\b", "Möchtest du"), (r"\bmöchten Sie\b", "möchtest du"),
        (r"\bWuerden Sie\b", "Wuerdest du"), (r"\bwuerden Sie\b", "wuerdest du"),
        (r"\bWürden Sie\b", "Würdest du"), (r"\bwürden Sie\b", "würdest du"),
        (r"\bDuerfen Sie\b", "Darfst du"), (r"\bduerfen Sie\b", "darfst du"),
        (r"\bDürfen Sie\b", "Darfst du"), (r"\bdürfen Sie\b", "darfst du"),
        (r"\bWollen Sie\b", "Willst du"), (r"\bwollen Sie\b", "willst du"),
        (r"\bSollten Sie\b", "Solltest du"), (r"\bsollten Sie\b", "solltest du"),
        (r"\bSind Sie\b", "Bist du"), (r"\bsind Sie\b", "bist du"),
        (r"\bWerden Sie\b", "Wirst du"), (r"\bwerden Sie\b", "wirst du"),
        (r"\bWissen Sie\b", "Weißt du"), (r"\bwissen Sie\b", "weißt du"),
        (r"\bKennen Sie\b", "Kennst du"), (r"\bkennen Sie\b", "kennst du"),
        (r"\bFinden Sie\b", "Findest du"), (r"\bfinden Sie\b", "findest du"),
        (r"\bMeinen Sie\b", "Meinst du"), (r"\bmeinen Sie\b", "meinst du"),
        (r"\bGlauben Sie\b", "Glaubst du"), (r"\bglauben Sie\b", "glaubst du"),
        (r"\bBrauchen Sie\b", "Brauchst du"), (r"\bbrauchen Sie\b", "brauchst du"),
        (r"\bSuchen Sie\b", "Suchst du"), (r"\bsuchen Sie\b", "suchst du"),
        (r"\bGeben Sie\b", "Gib"), (r"\bgeben Sie\b", "gib"),
        (r"\bSagen Sie\b", "Sag"), (r"\bsagen Sie\b", "sag"),
        (r"\bSchauen Sie\b", "Schau"), (r"\bschauen Sie\b", "schau"),
        (r"\bNehmen Sie\b", "Nimm"), (r"\bnehmen Sie\b", "nimm"),
        (r"\bLassen Sie\b", "Lass"), (r"\blassen Sie\b", "lass"),
        (r"\bBeachten Sie\b", "Beachte"), (r"\bbeachten Sie\b", "beachte"),
        (r"\bSehen Sie\b", "Sieh"), (r"\bsehen Sie\b", "sieh"),
        (r"\bVersuchen Sie\b", "Versuch"), (r"\bversuchen Sie\b", "versuch"),
        (r"\bProbieren Sie\b", "Probier"), (r"\bprobieren Sie\b", "probier"),
        (r"\bWarten Sie\b", "Warte"), (r"\bwarten Sie\b", "warte"),
        (r"\bStellen Sie\b", "Stell"), (r"\bstellen Sie\b", "stell"),
        (r"\b[UÜ]berpr[uü]fen Sie\b", "Ueberpruef"), (r"\b[uü]berpr[uü]fen Sie\b", "ueberpruef"),
        (r"\b[OÖ]ffnen Sie\b", "Oeffne"), (r"\b[oö]ffnen Sie\b", "oeffne"),
        (r"\bSchlie[sß]en Sie\b", "Schliess"), (r"\bschlie[sß]en Sie\b", "schliess"),
        (r"\bDenken Sie\b", "Denk"), (r"\bdenken Sie\b", "denk"),
        (r"\bAchten Sie\b", "Achte"), (r"\bachten Sie\b", "achte"),
        (r"\bRufen Sie\b", "Ruf"), (r"\brufen Sie\b", "ruf"),
    ]
    for pattern, replacement in _verb_pairs:
        text = re.sub(pattern, replacement, text)
    return text


def apply_imperativ_catchall(text: str) -> str:
    """Imperativ-Catch-all: 'VERBen Sie' → 'VERBe'."""
    def _imperativ_replace(m):
        return m.group(1) + "e"
    return re.sub(r"\b(\w{4,})en Sie\b", _imperativ_replace, text)


def apply_formal_map(text: str) -> str:
    """Pronomen + kontextbasierte Sie→du Ersetzung."""
    _formal_map = [
        (r"\bIhnen\b", "dir"), (r"\bIhre\b", "deine"),
        (r"\bIhren\b", "deinen"), (r"\bIhrem\b", "deinem"),
        (r"\bIhrer\b", "deiner"), (r"\bIhres\b", "deines"),
        (r"(?<=[,;:!?.]\s)Sie\b", "du"),
        (r"(?<=\bfür\s)Sie\b", "dich"),
        (r"(?<=\ban\s)Sie\b", "dich"),
        (r"(?<=\büber\s)Sie\b", "dich"), (r"(?<=\bueber\s)Sie\b", "dich"),
        (r"(?<=\bauf\s)Sie\b", "dich"),
        (r"(?<=\bgegen\s)Sie\b", "dich"),
        (r"(?<=\bohne\s)Sie\b", "dich"),
        (r"(?<=\bum\s)Sie\b", "dich"),
        (r"(?<=\bich\s)Sie\b", "dich"),
        (r"(?<=\bwir\s)Sie\b", "dich"),
        (r"(?<=\bman\s)Sie\b", "dich"),
        (r"(?<=\bdass\s)Sie\b", "du"), (r"(?<=\bwenn\s)Sie\b", "du"),
        (r"(?<=\bob\s)Sie\b", "du"),
        (r"(?<=\bwofür\s)Sie\b", "du"),
        (r"(?<=\bwozu\s)Sie\b", "du"),
        (r"(?<=\bworüber\s)Sie\b", "du"),
        (r"(?<=\bwarum\s)Sie\b", "du"),
        (r"(?<=\bwie\s)Sie\b", "du"),
        (r"(?<=\bwas\s)Sie\b", "du"),
        (r"(?<=\bwo\s)Sie\b", "du"),
        (r"(?<=\bwann\s)Sie\b", "du"),
        (r"(?<=\bbitte\s)Sie\b", "du"),
        (r"^Sie\b", "Du"),
        (r"(?<=\.\s)Sie\b", "Du"),
    ]
    for pattern, replacement in _formal_map:
        text = re.sub(pattern, replacement, text)
    return text


def apply_verb_sie_akkusativ(text: str) -> str:
    """Konjugiertes Verb + Sie → dich (Akkusativ)."""
    text = re.sub(r"(\b\w{3,}e\s)Sie\b", r"\1dich", text)
    text = re.sub(r"(?<=\bmuss\s)Sie\b", "dich", text)
    text = re.sub(r"(?<=\bkann\s)Sie\b", "dich", text)
    text = re.sub(r"(?<=\bwill\s)Sie\b", "dich", text)
    text = re.sub(r"(?<=\bdarf\s)Sie\b", "dich", text)
    return text


def apply_catchall(text: str) -> str:
    """Finaler Catch-all: Restliches Sie → du."""
    return re.sub(r"\bSie\b", "du", text)


def full_sie_du_conversion(text: str) -> str:
    """Komplette Sie→du Pipeline (alle Schritte)."""
    text = apply_verb_pairs(text)
    text = apply_imperativ_catchall(text)
    text = apply_formal_map(text)
    text = apply_verb_sie_akkusativ(text)
    text = apply_catchall(text)
    return text


# ============================================================
# Regression: Variable-width Lookbehind Crash
# ============================================================

class TestLookbehindRegression:
    """Der alte Code hatte (?<=\\b\\w{3,}e\\s)Sie → re.error.
    Jetzt ist es eine Capture-Group: (\\b\\w{3,}e\\s)Sie → \\1dich.
    """

    def test_no_crash_on_verb_sie(self):
        """Darf NICHT crashen (Regression fuer variable-width lookbehind)."""
        result = apply_verb_sie_akkusativ("informiere Sie bitte")
        assert "Sie" not in result

    def test_informiere_sie(self):
        result = apply_verb_sie_akkusativ("Ich informiere Sie sofort.")
        assert result == "Ich informiere dich sofort."

    def test_bitte_sie(self):
        result = apply_verb_sie_akkusativ("Ich bitte Sie um Geduld.")
        assert result == "Ich bitte dich um Geduld."

    def test_lasse_sie(self):
        result = apply_verb_sie_akkusativ("Ich lasse Sie wissen.")
        assert result == "Ich lasse dich wissen."

    def test_muss_sie(self):
        result = apply_verb_sie_akkusativ("Ich muss Sie warnen.")
        assert result == "Ich muss dich warnen."

    def test_kann_sie(self):
        result = apply_verb_sie_akkusativ("Ich kann Sie informieren.")
        assert result == "Ich kann dich informieren."


# ============================================================
# Verb-Paare
# ============================================================

class TestVerbPairs:
    """Modalverben + Sie → du-Konjugation."""

    @pytest.mark.parametrize("input_text,expected", [
        ("Haben Sie Fragen?", "Hast du Fragen?"),
        ("Können Sie mir helfen?", "Kannst du mir helfen?"),
        ("Möchten Sie etwas?", "Möchtest du etwas?"),
        ("Würden Sie mir sagen?", "Würdest du mir sagen?"),
        ("Wollen Sie das?", "Willst du das?"),
        ("Sollten Sie Fragen haben", "Solltest du Fragen haben"),
        ("Sind Sie sicher?", "Bist du sicher?"),
        ("Werden Sie kommen?", "Wirst du kommen?"),
        ("Wissen Sie das?", "Weißt du das?"),
        ("Kennen Sie mich?", "Kennst du mich?"),
        ("Brauchen Sie Hilfe?", "Brauchst du Hilfe?"),
    ])
    def test_modal_verb_conversion(self, input_text, expected):
        result = apply_verb_pairs(input_text)
        assert result == expected

    @pytest.mark.parametrize("input_text,expected", [
        ("Geben Sie mir das", "Gib mir das"),
        ("Sagen Sie mir", "Sag mir"),
        ("Schauen Sie mal", "Schau mal"),
        ("Nehmen Sie Platz", "Nimm Platz"),
        ("Lassen Sie mich", "Lass mich"),
        ("Warten Sie bitte", "Warte bitte"),
    ])
    def test_imperativ_pairs(self, input_text, expected):
        result = apply_verb_pairs(input_text)
        assert result == expected

    def test_lowercase_verb_pair(self):
        result = apply_verb_pairs("...und koennen Sie mir helfen?")
        assert "kannst du" in result


# ============================================================
# Imperativ-Catch-all
# ============================================================

class TestImperativCatchall:
    """'VERBen Sie' → 'VERBe' fuer unbekannte Verben."""

    def test_praezisieren(self):
        result = apply_imperativ_catchall("Praezisieren Sie bitte.")
        assert result == "Praezisiere bitte."

    def test_nennen(self):
        result = apply_imperativ_catchall("Nennen Sie mir einen Grund.")
        assert result == "Nenne mir einen Grund."

    def test_ignoriert_kurze_woerter(self):
        """Woerter <4 Zeichen Stamm werden ignoriert."""
        # "den Sie" sollte NICHT zu "de" werden
        result = apply_imperativ_catchall("Ich den Sie kennen")
        # "den" hat nur 3 Zeichen Stamm (ohne "en") = 1 → kein Match
        assert "den" in result

    def test_informieren(self):
        result = apply_imperativ_catchall("Informieren Sie mich bitte.")
        assert result == "Informiere mich bitte."


# ============================================================
# Pronomen-Mapping
# ============================================================

class TestPronomenMapping:
    """Ihnen/Ihre/etc. → dir/deine/etc."""

    @pytest.mark.parametrize("input_text,expected", [
        ("Ich sage Ihnen Bescheid", "Ich sage dir Bescheid"),
        ("Ihre Anfrage wurde bearbeitet", "deine Anfrage wurde bearbeitet"),
        ("Fuer Ihren Komfort", "Fuer deinen Komfort"),
        ("In Ihrem Haus", "In deinem Haus"),
        ("Aus Ihrer Sicht", "Aus deiner Sicht"),
        ("Ihres Hauses", "deines Hauses"),
    ])
    def test_pronomen_replacement(self, input_text, expected):
        result = apply_formal_map(input_text)
        assert result == expected


# ============================================================
# Kontextbasierte Sie→du
# ============================================================

class TestKontextSieDu:
    """Sie nach bestimmten Woertern wird korrekt ersetzt."""

    def test_nach_praeposition_fuer(self):
        result = apply_formal_map("Das ist für Sie.")
        assert "dich" in result

    def test_nach_praeposition_an(self):
        result = apply_formal_map("Ich denke an Sie.")
        assert "dich" in result

    def test_nach_pronomen_ich(self):
        # "ich Sie" braucht genau "ich " vor "Sie" — Satzanfang-Grossschreibung
        result = apply_formal_map("dass ich Sie informiere")
        assert "dich" in result

    def test_nach_konjunktion_dass(self):
        result = apply_formal_map("Ich hoffe, dass Sie zufrieden sind")
        assert "du" in result

    def test_nach_w_wort(self):
        result = apply_formal_map("Ich frage mich, warum Sie das wollen")
        assert "du" in result

    def test_satzanfang(self):
        result = apply_formal_map("Sie sind der Boss.")
        assert result.startswith("Du")

    def test_nach_punkt_full_pipeline(self):
        # Nach-Punkt-Erkennung braucht die volle Pipeline
        result = full_sie_du_conversion("Erledigt. Sie sind dran.")
        assert "Du" in result or "du" in result


# ============================================================
# Vollstaendige Pipeline
# ============================================================

class TestFullPipeline:
    """Ende-zu-Ende Tests fuer die komplette Sie→du Konversion."""

    def test_complex_sentence(self):
        text = "Haben Sie noch Fragen? Ich stehe Ihnen gerne zur Verfügung."
        result = full_sie_du_conversion(text)
        assert "Sie" not in result
        assert "Ihnen" not in result
        assert "Hast du" in result
        assert "dir" in result

    def test_no_sie_unchanged(self):
        text = "Das Licht ist jetzt an."
        result = full_sie_du_conversion(text)
        assert result == text

    def test_mixed_contexts(self):
        text = "Möchten Sie, dass ich Ihnen helfe? Geben Sie mir Bescheid."
        result = full_sie_du_conversion(text)
        assert "Sie" not in result
        assert "Ihnen" not in result

    def test_multiple_sie_in_one_sentence(self):
        text = "Wenn Sie wollen, kann ich Sie informieren."
        result = full_sie_du_conversion(text)
        assert "Sie" not in result
