"""
Tests fuer Device Fast-Path — LLM-Skip bei einfachen Geraete-Befehlen.

Testet:
  - extract_device_intent(): Regex-basierte Intent-Extraktion
  - Korrekte Function-Names und Argumente
  - Fallthrough bei komplexen Befehlen (Helligkeit, Farbe, Temperatur)
  - Raum-Extraktion aus Praepositional-Phrasen
  - "alles aus" / "alle Lichter aus" Muster
"""

import pytest

from assistant.pre_classifier import PreClassifier, DeviceIntent


@pytest.fixture
def classifier():
    return PreClassifier()


# ============================================================
# Licht an/aus
# ============================================================


class TestLightOnOff:
    """Einfache Licht-Befehle → set_light."""

    @pytest.mark.parametrize(
        "text, expected_state",
        [
            ("Licht an", "on"),
            ("Licht aus", "off"),
            ("Mach das Licht an", "on"),
            ("Mach das Licht aus", "off"),
            ("Lampe an", "on"),
            ("Lampe aus", "off"),
            ("Schalte das Licht ein", "on"),
            ("Schalte das Licht aus", "off"),
        ],
    )
    def test_light_with_room_fallback(self, classifier, text, expected_state):
        result = classifier.extract_device_intent(text, room="wohnzimmer")
        assert result is not None, f"'{text}' sollte erkannt werden"
        assert result.function == "set_light"
        assert result.args["state"] == expected_state
        assert result.args["room"] == "wohnzimmer"

    def test_light_with_room_in_text(self, classifier):
        result = classifier.extract_device_intent("Licht im Wohnzimmer an")
        assert result is not None
        assert result.function == "set_light"
        assert result.args["state"] == "on"
        assert result.args["room"] == "wohnzimmer"

    def test_light_in_der_kueche(self, classifier):
        result = classifier.extract_device_intent("Mach das Licht in der Kueche aus")
        assert result is not None
        assert result.function == "set_light"
        assert result.args["state"] == "off"
        assert result.args["room"] == "kueche"

    def test_no_room_no_fallback_returns_none(self, classifier):
        result = classifier.extract_device_intent("Licht an", room=None)
        assert result is None, "Ohne Raum-Kontext kann kein Intent extrahiert werden"


# ============================================================
# Rollladen hoch/runter
# ============================================================


class TestCoverUpDown:
    """Rollladen-Befehle → set_cover."""

    @pytest.mark.parametrize(
        "text, expected_pos",
        [
            ("Rollladen hoch", 100),
            ("Rollladen runter", 0),
            ("Rolladen hoch", 100),
            ("Rollo runter", 0),
            ("Jalousie hoch", 100),
            ("Fahr die Rollladen hoch", 100),
        ],
    )
    def test_cover_commands(self, classifier, text, expected_pos):
        result = classifier.extract_device_intent(text, room="schlafzimmer")
        assert result is not None, f"'{text}' sollte erkannt werden"
        assert result.function == "set_cover"
        assert result.args["position"] == expected_pos
        assert result.args["room"] == "schlafzimmer"

    def test_cover_stop(self, classifier):
        result = classifier.extract_device_intent("Rollladen stopp", room="wohnzimmer")
        assert result is not None
        assert result.function == "set_cover"
        assert result.args.get("action") == "stop"

    def test_cover_with_room(self, classifier):
        result = classifier.extract_device_intent("Rollladen im Bad hoch")
        assert result is not None
        assert result.function == "set_cover"
        assert result.args["room"] == "bad"
        assert result.args["position"] == 100


# ============================================================
# Switch (Steckdose, Kaffeemaschine)
# ============================================================


class TestSwitchOnOff:
    """Switch-Befehle → set_switch."""

    @pytest.mark.parametrize(
        "text, expected_state",
        [
            ("Steckdose an", "on"),
            ("Steckdose aus", "off"),
            ("Kaffeemaschine an", "on"),
            ("Kaffeemaschine aus", "off"),
            ("Ventilator an", "on"),
            ("Ventilator aus", "off"),
        ],
    )
    def test_switch_commands(self, classifier, text, expected_state):
        result = classifier.extract_device_intent(text, room="kueche")
        assert result is not None, f"'{text}' sollte erkannt werden"
        assert result.function == "set_switch"
        assert result.args["state"] == expected_state


# ============================================================
# "Alles aus" / "Alle Lichter aus"
# ============================================================


class TestAllOff:
    """Globale Befehle."""

    def test_alles_aus(self, classifier):
        result = classifier.extract_device_intent("Alles aus", room="wohnzimmer")
        assert result is not None
        assert result.function == "set_light"
        assert result.args["room"] == "all"
        assert result.args["state"] == "off"

    def test_alle_lichter_aus(self, classifier):
        result = classifier.extract_device_intent("Alle Lichter aus", room="wohnzimmer")
        assert result is not None
        assert result.function == "set_light"
        assert result.args["room"] == "all"
        assert result.args["state"] == "off"

    def test_ueberall_aus(self, classifier):
        result = classifier.extract_device_intent(
            "Ueberall Licht aus", room="wohnzimmer"
        )
        assert result is not None
        assert result.function == "set_light"
        assert result.args["room"] == "all"


# ============================================================
# Compound-Verben
# ============================================================


class TestCompoundVerbs:
    """Eingebettete/konjugierte Verben."""

    def test_einschalten(self, classifier):
        result = classifier.extract_device_intent(
            "Ich will dass du das Licht einschaltest", room="wohnzimmer"
        )
        assert result is not None
        assert result.function == "set_light"
        assert result.args["state"] == "on"

    def test_ausschalten(self, classifier):
        result = classifier.extract_device_intent(
            "Kannst du die Lampe ausschalten", room="wohnzimmer"
        )
        assert result is not None
        assert result.function == "set_light"
        assert result.args["state"] == "off"

    def test_hochfahren(self, classifier):
        result = classifier.extract_device_intent("Rollladen hochfahren", room="buero")
        assert result is not None
        assert result.function == "set_cover"
        assert result.args["position"] == 100


# ============================================================
# Fallthrough: Komplexe Befehle → None (braucht LLM)
# ============================================================


class TestFallthroughToLLM:
    """Befehle die NICHT per Fast-Path verarbeitet werden sollen."""

    @pytest.mark.parametrize(
        "text",
        [
            "Licht auf 50%",
            "Licht auf 50 Prozent",
            "Licht dimmen",
            "Licht heller",
            "Licht dunkler",
            "Licht rot",
            "Licht blau",
            "Heizung auf 22 Grad",
            "Temperatur auf 20°",
            "Heizung wärmer",
            "Heizung kälter",
        ],
    )
    def test_complex_commands_return_none(self, classifier, text):
        result = classifier.extract_device_intent(text, room="wohnzimmer")
        assert result is None, f"'{text}' sollte None zurueckgeben (braucht LLM)"

    def test_no_device_noun_returns_none(self, classifier):
        result = classifier.extract_device_intent(
            "Wie wird das Wetter morgen?", room="wohnzimmer"
        )
        assert result is None

    def test_empty_text(self, classifier):
        result = classifier.extract_device_intent("", room="wohnzimmer")
        assert result is None


# ============================================================
# Confidence
# ============================================================


class TestConfidence:
    """Intent-Confidence Werte."""

    def test_high_confidence(self, classifier):
        result = classifier.extract_device_intent("Licht an", room="wohnzimmer")
        assert result is not None
        assert result.confidence >= 0.9
