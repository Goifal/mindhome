"""
Tests fuer brain.py: _filter_response() und _safe_create_task().
Testet Response-Filtering, Think-Tag-Entfernung, Sprach-Check, Banned Phrases.
"""

import asyncio
import logging
import re
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------
# _safe_create_task Tests (Funktion inline definiert, da brain.py
# zu viele Dependencies hat fuer einen reinen Unit-Test)
# ---------------------------------------------------------------


def _safe_create_task(coro, *, name: str = ""):
    """Kopie aus brain.py — für isoliertes Testen."""
    task = asyncio.create_task(coro, name=name or None)

    def _on_done(t: asyncio.Task):
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logging.getLogger("test").error(
                "Fire-and-forget Task %r fehlgeschlagen: %s", t.get_name(), exc, exc_info=exc
            )

    task.add_done_callback(_on_done)
    return task


class TestSafeCreateTask:
    """_safe_create_task wrapt asyncio.create_task mit Error-Logging."""

    @pytest.mark.asyncio
    async def test_successful_task_no_error(self):
        async def ok_coro():
            return 42

        task = _safe_create_task(ok_coro(), name="test_ok")
        result = await task
        assert result == 42

    @pytest.mark.asyncio
    async def test_failed_task_logs_error(self, caplog):
        async def fail_coro():
            raise ValueError("test error")

        with caplog.at_level(logging.ERROR):
            task = _safe_create_task(fail_coro(), name="test_fail")
            await asyncio.sleep(0.05)

        assert any("test_fail" in r.message and "test error" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_task_name_is_set(self):
        async def noop():
            pass

        task = _safe_create_task(noop(), name="my_custom_name")
        assert task.get_name() == "my_custom_name"

    @pytest.mark.asyncio
    async def test_cancelled_task_no_log(self, caplog):
        async def slow_coro():
            await asyncio.sleep(10)

        with caplog.at_level(logging.ERROR):
            task = _safe_create_task(slow_coro(), name="test_cancel")
            task.cancel()
            await asyncio.sleep(0.05)

        assert not any("test_cancel" in r.message for r in caplog.records)


# ---------------------------------------------------------------
# _filter_response Tests (isoliert, ohne brain-Instanz)
# ---------------------------------------------------------------

# Wir testen die Filter-Logik direkt als reine Funktionen,
# da _filter_response auf self und yaml_config zugreift.


class TestThinkTagRemoval:
    """<think>...</think> Tags werden entfernt."""

    def test_complete_think_tag(self):
        text = "<think>internal reasoning here</think>Die Antwort ist 42."
        result = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        assert result == "Die Antwort ist 42."

    def test_multiline_think_tag(self):
        text = "<think>\nStep 1: think\nStep 2: more\n</think>\nAlles erledigt."
        result = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        assert result == "Alles erledigt."

    def test_multiple_think_tags(self):
        text = "<think>first</think>Hallo <think>second</think>Welt"
        result = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        assert result == "Hallo Welt"

    def test_unclosed_think_tag(self):
        text = "<think>partial reasoning without close"
        result = re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()
        assert result == ""

    def test_no_think_tag_unchanged(self):
        text = "Ganz normale Antwort ohne Tags."
        result = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        assert result == text


class TestBannedPhrases:
    """Banned Phrases werden case-insensitive entfernt."""

    _BANNED = [
        "Natürlich!", "Gerne!", "Selbstverständlich!",
        "Kann ich sonst noch etwas für dich tun?",
        "Als KI", "Ich bin ein Sprachmodell",
    ]

    def _remove_banned(self, text: str) -> str:
        for phrase in self._BANNED:
            idx = text.lower().find(phrase.lower())
            while idx != -1:
                text = text[:idx] + text[idx + len(phrase):]
                idx = text.lower().find(phrase.lower())
        return text.strip()

    def test_removes_natuerlich(self):
        result = self._remove_banned("Natürlich! Das Licht ist an.")
        assert result == "Das Licht ist an."

    def test_removes_gerne(self):
        result = self._remove_banned("Gerne! Erledigt.")
        assert result == "Erledigt."

    def test_removes_tail_question(self):
        result = self._remove_banned("Erledigt. Kann ich sonst noch etwas für dich tun?")
        assert result == "Erledigt."

    def test_removes_als_ki(self):
        result = self._remove_banned("Als KI kann ich das nicht.")
        assert result == "kann ich das nicht."

    def test_case_insensitive(self):
        result = self._remove_banned("NATÜRLICH! Erledigt.")
        assert result == "Erledigt."

    def test_no_match_leaves_unchanged(self):
        original = "Das Licht im Wohnzimmer ist jetzt aus."
        result = self._remove_banned(original)
        assert result == original


class TestBannedStarters:
    """Banned Starters am Satzanfang werden entfernt, Rest capitalized."""

    _STARTERS = ["Also,", "Also ", "Grundsätzlich", "Nun,", "Eigentlich"]

    def _remove_starters(self, text: str) -> str:
        for starter in self._STARTERS:
            if text.lstrip().lower().startswith(starter.lower()):
                text = text.lstrip()[len(starter):].lstrip()
                if text:
                    text = text[0].upper() + text[1:]
        return text

    def test_removes_also(self):
        result = self._remove_starters("Also, das Licht ist an.")
        assert result == "Das Licht ist an."

    def test_removes_eigentlich(self):
        result = self._remove_starters("Eigentlich ist alles ok.")
        assert result == "Ist alles ok."

    def test_capitalizes_after_removal(self):
        result = self._remove_starters("Nun, es ist 20 Grad.")
        assert result == "Es ist 20 Grad."

    def test_no_starter_unchanged(self):
        original = "Die Temperatur ist 22 Grad."
        result = self._remove_starters(original)
        assert result == original


class TestLanguageCheck:
    """Sprach-Check: Englische Antworten werden erkannt."""

    _EN_MARKERS = [
        " the ", " you ", " your ", " which ", " would ",
        " could ", " should ", " have ", " this ", " that ",
    ]
    _DE_MARKERS = [
        " der ", " die ", " das ", " ist ", " und ",
        " nicht ", " ich ", " hab ", " dir ", " ein ",
    ]

    def _is_english(self, text: str) -> bool:
        if len(text) <= 15:
            return False
        text_lower = f" {text.lower()} "
        en_hits = sum(1 for m in self._EN_MARKERS if m in text_lower)
        de_hits = sum(1 for m in self._DE_MARKERS if m in text_lower)
        de_hits += min(3, sum(1 for c in text if c in "äöüÄÖÜß"))
        return en_hits >= 2 and en_hits > de_hits

    def test_german_text_passes(self):
        assert not self._is_english("Das Licht im Wohnzimmer ist jetzt eingeschaltet.")

    def test_english_text_detected(self):
        assert self._is_english("The user would like to have the light turned on, which should be possible.")

    def test_mixed_with_german_majority_passes(self):
        assert not self._is_english("Die Temperatur ist auf 22 Grad eingestellt, das ist gut.")

    def test_short_text_skipped(self):
        assert not self._is_english("Hello there")  # zu kurz

    def test_umlauts_boost_german(self):
        # Text mit Umlauten: de_hits werden um Umlaut-Bonus erhöht
        assert not self._is_english("Natürlich, die Tür ist jetzt offen für dich.")

    def test_pure_english_reasoning(self):
        assert self._is_english("The user wants to turn on the light which would require calling the service.")


class TestSentenceLimit:
    """Max-Sentences-Begrenzung."""

    def _limit_sentences(self, text: str, max_sentences: int) -> str:
        if max_sentences > 0:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            if len(sentences) > max_sentences:
                text = " ".join(sentences[:max_sentences])
        return text

    def test_no_limit(self):
        text = "Satz eins. Satz zwei. Satz drei."
        assert self._limit_sentences(text, 0) == text

    def test_limit_to_two(self):
        text = "Satz eins. Satz zwei. Satz drei. Satz vier."
        result = self._limit_sentences(text, 2)
        assert result == "Satz eins. Satz zwei."

    def test_limit_to_one(self):
        text = "Erster Satz! Zweiter Satz."
        result = self._limit_sentences(text, 1)
        assert result == "Erster Satz!"

    def test_under_limit_unchanged(self):
        text = "Nur ein Satz."
        assert self._limit_sentences(text, 5) == text


class TestSorryRemoval:
    """'Es tut mir leid' Varianten werden entfernt."""

    _PATTERNS = [
        "es tut mir leid,", "es tut mir leid.", "leider ",
        "entschuldigung,", "tut mir leid,",
    ]

    def _remove_sorry(self, text: str) -> str:
        for pattern in self._PATTERNS:
            idx = text.lower().find(pattern)
            if idx != -1:
                text = text[:idx] + text[idx + len(pattern):].lstrip()
                if text:
                    text = text[0].upper() + text[1:]
        return text

    def test_removes_es_tut_mir_leid(self):
        result = self._remove_sorry("Es tut mir leid, das kann ich nicht.")
        assert result == "Das kann ich nicht."

    def test_removes_leider(self):
        result = self._remove_sorry("Leider ist das nicht möglich.")
        assert result == "Ist das nicht möglich."

    def test_removes_entschuldigung(self):
        result = self._remove_sorry("Entschuldigung, Fehler aufgetreten.")
        assert result == "Fehler aufgetreten."

    def test_capitalizes_rest(self):
        result = self._remove_sorry("Tut mir leid, die Heizung ist aus.")
        assert result == "Die Heizung ist aus."


class TestImplicitReasoning:
    """Implizites englisches Reasoning wird erkannt und deutsche Antwort extrahiert."""

    _REASONING_STARTERS = [
        "Okay, the user", "The user", "Let me ", "I need to",
        "First, I", "Hmm,", "Alright,",
    ]

    def _starts_with_reasoning(self, text: str) -> bool:
        for starter in self._REASONING_STARTERS:
            if text.lstrip().startswith(starter):
                return True
        return False

    def test_english_reasoning_detected(self):
        assert self._starts_with_reasoning("Okay, the user wants to turn on the light")

    def test_german_not_detected(self):
        assert not self._starts_with_reasoning("Das Licht ist jetzt an.")

    def test_let_me_detected(self):
        assert self._starts_with_reasoning("Let me check the current temperature")

    def test_hmm_detected(self):
        assert self._starts_with_reasoning("Hmm, I should check the state first")
