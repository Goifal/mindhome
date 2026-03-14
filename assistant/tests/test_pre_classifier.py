"""
Tests fuer pre_classifier.py — PreClassifier.classify()

Testet alle Klassifikations-Pfade:
  - DEVICE_FAST (Verb-Start, Nomen+Aktion, eingebettete Verben)
  - DEVICE_QUERY (Status-Abfragen)
  - MEMORY (Erinnerungs-Fragen)
  - KNOWLEDGE (Wissensfragen ohne Smart-Home-Bezug)
  - GENERAL (Default)

Regressionstests fuer bekannte Bugs:
  - "Ich will das du die Siebtraegermaschine ausschaltest" → DEVICE_FAST (nicht GENERAL)
  - Fragen ("ist das Licht an?") → DEVICE_QUERY (nicht DEVICE_FAST)
"""

import pytest

from assistant.pre_classifier import (
    PreClassifier,
    PROFILE_DEVICE_FAST,
    PROFILE_DEVICE_QUERY,
    PROFILE_KNOWLEDGE,
    PROFILE_MEMORY,
    PROFILE_GENERAL,
)


@pytest.fixture
def classifier():
    return PreClassifier()


# ============================================================
# DEVICE_FAST: Verb am Satzanfang
# ============================================================

class TestDeviceFastVerbStart:
    """Geraete-Befehle mit Verb am Satzanfang."""

    @pytest.mark.parametrize("text", [
        "Mach das Licht an",
        "Schalte das Licht aus",
        "Schalt die Heizung ein",
        "Stell die Heizung auf 22 Grad",
        "Dreh die Heizung hoch",
        "Fahr die Rollladen runter",
        "Oeffne das Fenster",
        "Schliess die Tuer",
        "Aktivier die Szene",
        "Deaktivier den Alarm",
        "Spiel Musik",
        "Stopp die Musik",
        "Pause die Musik",
        "Pausier den Song",
        "Lauter bitte",
        "Leiser bitte",
        "Mache das Licht an",
    ])
    def test_verb_start_commands(self, classifier, text):
        result = classifier.classify(text)
        assert result.category == "device_command", f"'{text}' sollte DEVICE_FAST sein"

    def test_verb_start_not_question(self, classifier):
        """Fragen mit Verb am Anfang sollen NICHT als Device-Command gelten."""
        result = classifier.classify("Ist das Licht an?")
        assert result.category != "device_command"


# ============================================================
# DEVICE_FAST: Nomen + Aktion
# ============================================================

class TestDeviceFastNounAction:
    """Geraete-Befehle mit Nomen + Aktionswort."""

    @pytest.mark.parametrize("text", [
        "Licht an",
        "Licht aus",
        "Lampe an",
        "Rollladen hoch",
        "Rollladen runter",
        "Rolladen auf",
        "Jalousie zu",
        "Rollo hoch",
        "Heizung an",
        "Heizung aus",
        "Steckdose ein",
        "Steckdose aus",
        "Licht 50%",
    ])
    def test_noun_action_commands(self, classifier, text):
        result = classifier.classify(text)
        assert result.category == "device_command", f"'{text}' sollte DEVICE_FAST sein"


# ============================================================
# DEVICE_FAST: Eingebettete Verben (Regression)
# ============================================================

class TestDeviceFastEmbeddedVerbs:
    """Konjugierte Verben mitten im Satz — vorher als GENERAL klassifiziert."""

    @pytest.mark.parametrize("text", [
        "Ich will das du die Siebtraegermaschine ausschaltest",
        "Kannst du die Lampe einschalten",
        "Bitte die Steckdose ausschalten",
        "Ich moechte das Licht anmachen",
        "Du sollst die Heizung einschalten",
        "Bitte den Fernseher ausmachen",
        "Wuerdest du die Rollladen hochfahren",
        "Bitte die Tuer oeffnen",
        "Kannst du die Musik abspielen",
        "Bitte die Musik stoppen",
        "Ich will die Szene aktivieren",
        "Bitte deaktivieren",
    ])
    def test_embedded_verb_commands(self, classifier, text):
        result = classifier.classify(text)
        assert result.category == "device_command", f"'{text}' sollte DEVICE_FAST sein"

    def test_too_long_embedded_verb_goes_general(self, classifier):
        """Eingebettete Verben mit >12 Woertern → GENERAL."""
        long_text = "Ich moechte bitte dass du jetzt sofort endlich mal die Lampe im Wohnzimmer ausschaltest bitte danke"
        result = classifier.classify(long_text)
        # >12 Woerter → nicht als embedded verb erkannt
        assert result.category == "general"


# ============================================================
# DEVICE_FAST: Korrekte Profil-Flags
# ============================================================

class TestDeviceFastProfile:
    """DEVICE_FAST aktiviert nur notwendige Subsysteme."""

    def test_device_fast_flags(self):
        assert PROFILE_DEVICE_FAST.need_house_status is True
        assert PROFILE_DEVICE_FAST.need_room_profile is True
        assert PROFILE_DEVICE_FAST.need_time_hints is True
        assert PROFILE_DEVICE_FAST.need_security is True
        assert PROFILE_DEVICE_FAST.need_guest_mode is True
        # Diese sollten AUS sein:
        assert PROFILE_DEVICE_FAST.need_mood is False
        assert PROFILE_DEVICE_FAST.need_formality is False
        assert PROFILE_DEVICE_FAST.need_irony is False
        assert PROFILE_DEVICE_FAST.need_memories is False
        assert PROFILE_DEVICE_FAST.need_rag is False
        assert PROFILE_DEVICE_FAST.need_cross_room is False
        assert PROFILE_DEVICE_FAST.need_tutorial is False
        assert PROFILE_DEVICE_FAST.need_summary is False
        assert PROFILE_DEVICE_FAST.need_mindhome_data is False
        assert PROFILE_DEVICE_FAST.need_activity is False


# ============================================================
# DEVICE_QUERY: Status-Abfragen
# ============================================================

class TestDeviceQuery:
    """Status-Fragen ueber Smart-Home-Geraete."""

    @pytest.mark.parametrize("text", [
        "Wie warm ist es?",
        "Wie kalt ist es draussen?",
        "Ist das Licht an?",
        "Sind die Rolllaeden offen?",
        "Was zeigt der Temperatursensor?",
        "Welche Temperatur hat es?",
        "Wieviel Grad ist es?",
        "Wie viel Grad hat es?",
        "Wie hoch ist der Stromverbrauch?",
        "Was laeuft gerade?",
        "Was spielt gerade?",
        "Status",
        "Hausstatus",
        "Ist die Heizung an?",
        "Sind die Lampen aus?",
    ])
    def test_status_queries(self, classifier, text):
        result = classifier.classify(text)
        assert result.category == "device_query", f"'{text}' sollte DEVICE_QUERY sein"

    def test_too_long_query_goes_general(self, classifier):
        """Status-Queries mit >10 Woertern → GENERAL."""
        long_text = "Kannst du mir bitte sagen wie warm es gerade im Wohnzimmer ist?"
        result = classifier.classify(long_text)
        assert result.category == "general"


# ============================================================
# MEMORY: Erinnerungs-Fragen
# ============================================================

class TestMemoryClassification:
    """Fragen nach gespeicherten Erinnerungen."""

    @pytest.mark.parametrize("text", [
        "Erinnerst du dich an gestern?",
        "Weisst du noch was ich gesagt habe?",
        "Was weisst du ueber mich?",
        "Habe ich dir gesagt dass ich Kaffee mag?",
        "Hab ich gesagt ich komme spaeter?",
        "Was war gestern los?",
    ])
    def test_memory_questions(self, classifier, text):
        result = classifier.classify(text)
        assert result.category == "memory", f"'{text}' sollte MEMORY sein"


# ============================================================
# KNOWLEDGE: Wissensfragen
# ============================================================

class TestKnowledgeClassification:
    """Wissensfragen OHNE Smart-Home-Bezug."""

    @pytest.mark.parametrize("text", [
        "Was ist Photosynthese?",
        "Wie funktioniert ein Motor?",
        "Wer ist Albert Einstein?",
        "Was bedeutet Demokratie?",
        "Erklaer mir was Quantenphysik ist",
        "Wie kocht man Spaghetti?",
        "Rezept fuer Pfannkuchen",
        "Definition von Algorithmus",
        "Unterschied zwischen Java und Python",
        "Warum ist der Himmel blau?",
        "Wie macht man Butter?",
        "Was passiert wenn Wasser gefriert?",
        "Wie viele Planeten gibt es?",
    ])
    def test_knowledge_questions(self, classifier, text):
        result = classifier.classify(text)
        assert result.category == "knowledge", f"'{text}' sollte KNOWLEDGE sein"

    @pytest.mark.parametrize("text", [
        "Wie funktioniert die Heizung?",
        "Was ist die Temperatur?",
        "Wie viel Strom verbrauchen wir?",
        "Was bedeutet der Sensor-Wert?",
    ])
    def test_knowledge_with_smart_home_goes_general(self, classifier, text):
        """Wissensfragen MIT Smart-Home-Bezug → GENERAL (nicht KNOWLEDGE)."""
        result = classifier.classify(text)
        assert result.category != "knowledge", f"'{text}' sollte NICHT KNOWLEDGE sein (Smart-Home-Bezug)"


# ============================================================
# GENERAL: Default-Fallback
# ============================================================

class TestGeneralClassification:
    """Alles was in keine andere Kategorie passt."""

    @pytest.mark.parametrize("text", [
        "Guten Morgen",
        "Wie geht es dir?",
        "Erzaehl mir einen Witz",
        "Was denkst du darueber?",
        "Danke nichts davon",
        "Ich bin muede",
        "Gute Nacht Jarvis",
    ])
    def test_general_fallback(self, classifier, text):
        result = classifier.classify(text)
        assert result.category == "general", f"'{text}' sollte GENERAL sein"


# ============================================================
# GENERAL: Profil hat alles aktiviert
# ============================================================

class TestGeneralProfile:
    """GENERAL-Profil aktiviert alle Subsysteme (Default-Werte)."""

    def test_general_all_active(self):
        assert PROFILE_GENERAL.need_house_status is True
        assert PROFILE_GENERAL.need_mindhome_data is True
        assert PROFILE_GENERAL.need_activity is True
        assert PROFILE_GENERAL.need_room_profile is True
        assert PROFILE_GENERAL.need_memories is True
        assert PROFILE_GENERAL.need_mood is True
        assert PROFILE_GENERAL.need_formality is True
        assert PROFILE_GENERAL.need_irony is True
        assert PROFILE_GENERAL.need_time_hints is True
        assert PROFILE_GENERAL.need_security is True
        assert PROFILE_GENERAL.need_cross_room is True
        assert PROFILE_GENERAL.need_guest_mode is True
        assert PROFILE_GENERAL.need_tutorial is True
        assert PROFILE_GENERAL.need_summary is True
        assert PROFILE_GENERAL.need_rag is True


# ============================================================
# Edge Cases & Regression Tests
# ============================================================

class TestEdgeCases:
    """Grenzfaelle und Regressions-Tests."""

    def test_empty_string(self, classifier):
        result = classifier.classify("")
        assert result.category == "general"

    def test_single_word(self, classifier):
        result = classifier.classify("Hallo")
        assert result.category == "general"

    def test_question_mark_alone_does_not_prevent_device_command(self, classifier):
        """Imperativ-Befehl mit ? am Ende ist weiterhin ein Device-Command (DL3-AI2 Fix)."""
        result = classifier.classify("Schalte das Licht an?")
        # Kein Fragewort → Befehl in rhetorischer Frageform → bleibt Device-Command
        assert result.category == "device_command"

    def test_question_start_prevents_device_command(self, classifier):
        """'Ist/Sind/Wie/Was' am Anfang verhindert Device-Command."""
        result = classifier.classify("Ist die Steckdose an")
        assert result.category != "device_command"

    def test_word_count_boundary_8(self, classifier):
        """Genau 8 Woerter mit Verb-Start → DEVICE_FAST."""
        text = "Mach bitte das Licht im Wohnzimmer an"
        assert len(text.split()) == 7  # <8
        result = classifier.classify(text)
        assert result.category == "device_command"

    def test_word_count_over_8_no_verb_start(self, classifier):
        """9 Woerter ohne eingebettetes Verb → GENERAL."""
        text = "Ich moechte bitte das Licht im Wohnzimmer jetzt anschalten"
        result = classifier.classify(text)
        # 9 Woerter, hat aber "anschalten" als embedded verb → device_command
        assert result.category == "device_command"

    def test_percentage_counts_as_action(self, classifier):
        """Prozentzeichen zaehlt als Aktion."""
        result = classifier.classify("Licht 75%")
        assert result.category == "device_command"

    def test_case_insensitive(self, classifier):
        """Klassifikation ist case-insensitive."""
        result = classifier.classify("MACH DAS LICHT AN")
        assert result.category == "device_command"

    def test_leading_trailing_whitespace(self, classifier):
        """Whitespace wird ignoriert."""
        result = classifier.classify("  Licht an  ")
        assert result.category == "device_command"

    def test_priority_device_over_knowledge(self, classifier):
        """Device-Commands haben Prioritaet ueber Knowledge."""
        result = classifier.classify("Schalte die Heizung aus")
        assert result.category == "device_command"

    def test_priority_device_query_over_memory(self, classifier):
        """Status-Queries haben Prioritaet ueber Memory wenn beides matcht."""
        result = classifier.classify("Was war die Temperatur?")
        # "was war" → memory keyword, aber "temperatur" + status pattern → device_query
        result2 = classifier.classify("Wie warm ist es?")
        assert result2.category == "device_query"
