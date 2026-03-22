"""
Tests fuer IntentTracker — Datum-Parsing, Intent-Parsing, Speicherung,
aktive Intents, faellige Intents, Lifecycle und Reminder-Loop.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from assistant.intent_tracker import IntentTracker, parse_relative_date


class TestParseRelativeDate:
    """Tests fuer parse_relative_date()."""

    def _ref(self):
        """Fester Referenz-Zeitpunkt: Mittwoch 2026-02-18."""
        return datetime(2026, 2, 18, 10, 0, 0)  # Mittwoch

    def test_heute(self):
        ref = self._ref()
        assert parse_relative_date("heute", ref) == "2026-02-18"

    def test_morgen(self):
        ref = self._ref()
        assert parse_relative_date("morgen", ref) == "2026-02-19"

    def test_uebermorgen(self):
        ref = self._ref()
        assert parse_relative_date("uebermorgen", ref) == "2026-02-20"

    def test_in_3_tagen(self):
        ref = self._ref()
        assert parse_relative_date("in 3 Tagen", ref) == "2026-02-21"

    def test_in_2_wochen(self):
        ref = self._ref()
        assert parse_relative_date("in 2 Wochen", ref) == "2026-03-04"

    def test_naechsten_freitag(self):
        ref = self._ref()  # Mittwoch
        result = parse_relative_date("am Freitag", ref)
        assert result == "2026-02-20"  # 2 Tage spaeter

    def test_naechsten_montag_springt_woche(self):
        ref = self._ref()  # Mittwoch
        result = parse_relative_date("am Montag", ref)
        assert result == "2026-02-23"  # Naechster Montag

    def test_naechstes_wochenende(self):
        ref = self._ref()  # Mittwoch
        result = parse_relative_date("naechstes Wochenende", ref)
        assert result == "2026-02-21"  # Samstag

    def test_naechste_woche(self):
        ref = self._ref()
        result = parse_relative_date("naechste Woche", ref)
        assert result == "2026-02-25"  # +7 Tage

    def test_ende_der_woche(self):
        ref = self._ref()  # Mittwoch
        result = parse_relative_date("Ende der Woche", ref)
        assert result == "2026-02-20"  # Freitag

    def test_unknown_returns_none(self):
        assert parse_relative_date("irgendwann") is None

    def test_empty_string(self):
        assert parse_relative_date("") is None


class TestParseIntents:
    """Tests fuer _parse_intents()."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        return t

    def test_valid_json_array(self, tracker):
        llm_output = json.dumps([{"intent": "Besuch", "deadline": "2026-03-01"}])
        result = tracker._parse_intents(llm_output, "Max")
        assert len(result) == 1
        assert result[0]["intent"] == "Besuch"
        assert result[0]["person"] == "Max"

    def test_empty_array(self, tracker):
        result = tracker._parse_intents("[]", "Max")
        assert result == []

    def test_json_with_surrounding_text(self, tracker):
        llm_output = 'Hier sind die Intents:\n[{"intent": "Arzt", "deadline": "2026-03-05"}]\nFertig.'
        result = tracker._parse_intents(llm_output, "Anna")
        assert len(result) == 1
        assert result[0]["intent"] == "Arzt"

    def test_invalid_json(self, tracker):
        result = tracker._parse_intents("Das ist kein JSON", "Max")
        assert result == []

    def test_filters_empty_intents(self, tracker):
        llm_output = json.dumps(
            [{"intent": "", "deadline": "2026-03-01"}, {"intent": "Urlaub"}]
        )
        result = tracker._parse_intents(llm_output, "Max")
        assert len(result) == 1
        assert result[0]["intent"] == "Urlaub"


class TestExtractIntents:
    """Tests fuer extract_intents() — Schnell-Filter."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        return t

    @pytest.mark.asyncio
    async def test_short_text_skipped(self, tracker):
        result = await tracker.extract_intents("Hallo du")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_time_keywords_skipped(self, tracker):
        """Text ohne Zeitangaben wird uebersprungen."""
        result = await tracker.extract_intents(
            "Wie wird das Wetter in Berlin sein dieses Jahr?"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_text_with_time_keyword_calls_llm(self, tracker):
        """Text mit Zeitangabe geht an das LLM."""
        tracker.ollama.chat.return_value = {
            "message": {"content": "[]"},
        }
        result = await tracker.extract_intents(
            "Meine Eltern kommen morgen zu Besuch und bleiben eine Woche"
        )
        tracker.ollama.chat.assert_called_once()
        assert result == []


class TestTrackIntent:
    """Tests fuer track_intent() — Redis-Speicherung."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        t.redis = AsyncMock()
        return t

    @pytest.mark.asyncio
    async def test_stores_intent(self, tracker):
        intent = {"intent": "Besuch", "deadline": "2026-03-01"}
        result = await tracker.track_intent(intent)
        assert result is True
        tracker.redis.hset.assert_called_once()
        tracker.redis.sadd.assert_called_once()
        tracker.redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_redis_returns_false(self, tracker):
        tracker.redis = None
        result = await tracker.track_intent({"intent": "Test"})
        assert result is False


class TestDismissIntent:
    """Tests fuer dismiss_intent()."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        t.redis = AsyncMock()
        return t

    @pytest.mark.asyncio
    async def test_dismiss_marks_and_removes(self, tracker):
        result = await tracker.dismiss_intent("intent_123")
        assert result is True
        tracker.redis.hset.assert_called_once()
        tracker.redis.srem.assert_called_once()

    @pytest.mark.asyncio
    async def test_dismiss_no_redis(self, tracker):
        tracker.redis = None
        result = await tracker.dismiss_intent("intent_123")
        assert result is False

    @pytest.mark.asyncio
    async def test_dismiss_redis_error_returns_false(self, tracker):
        """Redis-Fehler beim Dismiss gibt False zurueck statt Exception."""
        tracker.redis.hset.side_effect = Exception("Redis down")
        result = await tracker.dismiss_intent("intent_123")
        assert result is False


class TestGetActiveIntents:
    """Tests fuer get_active_intents() — Laden aktiver Intents aus Redis."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        t.redis = AsyncMock()
        return t

    @pytest.mark.asyncio
    async def test_no_redis_returns_empty(self, tracker):
        tracker.redis = None
        result = await tracker.get_active_intents()
        assert result == []

    @pytest.mark.asyncio
    async def test_no_active_intents(self, tracker):
        """Leeres Set ergibt leere Liste."""
        tracker.redis.smembers.return_value = set()
        result = await tracker.get_active_intents()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_stored_intents(self, tracker):
        """Gespeicherte Intents werden korrekt geladen und JSON-dekodiert."""
        tracker.redis.smembers.return_value = {b"intent_001"}

        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        pipe_mock.execute = AsyncMock(
            return_value=[
                {
                    b"intent": b"Besuch der Eltern",
                    b"deadline": b"2026-03-25",
                    b"status": b"active",
                    b"intent_id": b"intent_001",
                    b"suggested_actions": b'["Gaestemodus vorbereiten"]',
                }
            ]
        )
        tracker.redis.pipeline = MagicMock(return_value=pipe_mock)

        result = await tracker.get_active_intents()
        assert len(result) == 1
        assert result[0]["intent"] == "Besuch der Eltern"
        assert result[0]["deadline"] == "2026-03-25"
        # JSON-Feld sollte als Liste dekodiert werden
        assert isinstance(result[0]["suggested_actions"], list)

    @pytest.mark.asyncio
    async def test_expired_intent_removed_from_set(self, tracker):
        """Wenn hgetall leer ist (expired), wird der Intent aus dem Set entfernt."""
        tracker.redis.smembers.return_value = {b"intent_expired"}

        pipe_mock = MagicMock()
        pipe_mock.hgetall = MagicMock()
        # Leeres Dict = Intent existiert nicht mehr (TTL abgelaufen)
        pipe_mock.execute = AsyncMock(return_value=[{}])
        tracker.redis.pipeline = MagicMock(return_value=pipe_mock)

        result = await tracker.get_active_intents()
        assert result == []
        tracker.redis.srem.assert_called_once_with(
            "mha:intents:active", "intent_expired"
        )

    @pytest.mark.asyncio
    async def test_redis_error_returns_empty(self, tracker):
        """Redis-Fehler gibt leere Liste zurueck statt Exception."""
        tracker.redis.smembers.side_effect = Exception("Connection lost")
        result = await tracker.get_active_intents()
        assert result == []


class TestGetDueIntents:
    """Tests fuer get_due_intents() — faellige Intents pruefen."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        t.redis = AsyncMock()
        t.remind_hours_before = 12
        return t

    @pytest.mark.asyncio
    async def test_no_active_intents(self, tracker):
        """Keine aktiven Intents ergibt leere Liste."""
        with patch.object(tracker, "get_active_intents", return_value=[]):
            result = await tracker.get_due_intents()
        assert result == []

    @pytest.mark.asyncio
    async def test_intent_within_reminder_window(self, tracker):
        """Intent innerhalb des Erinnerungsfensters wird zurueckgegeben."""
        # strptime erzeugt naive Datetimes, also muss now() ebenfalls naiv sein
        # damit der Vergleich in get_due_intents funktioniert.
        fake_now = datetime(2026, 3, 20, 10, 0, 0)
        # Deadline 6 Stunden in der Zukunft (innerhalb von 12h-Fenster)
        deadline = (fake_now + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M")

        intent = {
            "intent": "Arzttermin",
            "deadline": deadline,
            "intent_id": "intent_due",
            "status": "active",
        }
        tracker.redis.get.return_value = None  # Nicht schon erinnert

        with patch.object(tracker, "get_active_intents", return_value=[intent]):
            with patch("assistant.intent_tracker.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.strptime = datetime.strptime
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = await tracker.get_due_intents()

        assert len(result) == 1
        assert result[0]["intent"] == "Arzttermin"
        assert "time_until_hours" in result[0]
        # Reminded-Flag sollte gesetzt werden
        tracker.redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_intent_outside_reminder_window(self, tracker):
        """Intent weit in der Zukunft wird nicht zurueckgegeben."""
        fake_now = datetime(2026, 3, 20, 10, 0, 0)
        # Deadline 5 Tage in der Zukunft (weit ausserhalb von 12h-Fenster)
        deadline = (fake_now + timedelta(days=5)).strftime("%Y-%m-%d")

        intent = {
            "intent": "Urlaub",
            "deadline": deadline,
            "intent_id": "intent_far",
            "status": "active",
        }

        with patch.object(tracker, "get_active_intents", return_value=[intent]):
            with patch("assistant.intent_tracker.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.strptime = datetime.strptime
                result = await tracker.get_due_intents()

        assert result == []

    @pytest.mark.asyncio
    async def test_already_reminded_skipped(self, tracker):
        """Intent mit bereits gesetztem Reminded-Flag wird uebersprungen."""
        fake_now = datetime(2026, 3, 20, 10, 0, 0)
        deadline = (fake_now + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M")

        intent = {
            "intent": "Meeting",
            "deadline": deadline,
            "intent_id": "intent_reminded",
            "status": "active",
        }
        # Bereits erinnert
        tracker.redis.get.return_value = b"1"

        with patch.object(tracker, "get_active_intents", return_value=[intent]):
            with patch("assistant.intent_tracker.datetime") as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.strptime = datetime.strptime
                result = await tracker.get_due_intents()

        assert result == []

    @pytest.mark.asyncio
    async def test_expired_intent_auto_dismissed(self, tracker):
        """Intent mit abgelaufener Deadline (>2 Tage) wird automatisch dismissed."""
        fake_now = datetime(2026, 3, 20, 10, 0, 0)
        # Deadline 3 Tage in der Vergangenheit
        deadline = (fake_now - timedelta(days=3)).strftime("%Y-%m-%d")

        intent = {
            "intent": "Alter Termin",
            "deadline": deadline,
            "intent_id": "intent_old",
            "status": "active",
        }

        with patch.object(tracker, "get_active_intents", return_value=[intent]):
            with patch.object(
                tracker, "dismiss_intent", new_callable=AsyncMock
            ) as mock_dismiss:
                with patch("assistant.intent_tracker.datetime") as mock_dt:
                    mock_dt.now.return_value = fake_now
                    mock_dt.strptime = datetime.strptime
                    result = await tracker.get_due_intents()

        assert result == []
        mock_dismiss.assert_called_once_with("intent_old")

    @pytest.mark.asyncio
    async def test_intent_without_deadline_skipped(self, tracker):
        """Intent ohne Deadline wird ignoriert."""
        intent = {
            "intent": "Irgendwas",
            "intent_id": "intent_no_dl",
            "status": "active",
        }

        with patch.object(tracker, "get_active_intents", return_value=[intent]):
            result = await tracker.get_due_intents()

        assert result == []


class TestTrackIntentMetadata:
    """Zusaetzliche Tests fuer track_intent() — Metadaten und Felder."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        t.redis = AsyncMock()
        return t

    @pytest.mark.asyncio
    async def test_intent_gets_id_and_status(self, tracker):
        """track_intent setzt intent_id, created_at und status auf dem Dict."""
        intent = {"intent": "Einkaufen", "deadline": "2026-04-01"}
        await tracker.track_intent(intent)

        assert "intent_id" in intent
        assert intent["intent_id"].startswith("intent_")
        assert intent["status"] == "active"
        assert "created_at" in intent

    @pytest.mark.asyncio
    async def test_intent_ttl_set_to_30_days(self, tracker):
        """TTL wird auf 30 Tage gesetzt."""
        intent = {"intent": "Test", "deadline": "2026-04-01"}
        await tracker.track_intent(intent)

        call_args = tracker.redis.expire.call_args
        assert call_args[0][1] == 30 * 86400

    @pytest.mark.asyncio
    async def test_redis_error_on_track_returns_false(self, tracker):
        """Redis-Fehler beim Speichern gibt False zurueck."""
        tracker.redis.hset.side_effect = Exception("Write failed")
        result = await tracker.track_intent({"intent": "Kaputt"})
        assert result is False


class TestIntentTrackerLifecycle:
    """Tests fuer initialize(), stop() und set_notify_callback()."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        return t

    @pytest.mark.asyncio
    async def test_initialize_without_redis_no_task(self, tracker):
        """Ohne Redis wird kein Hintergrund-Task gestartet."""
        await tracker.initialize(redis_client=None)
        assert tracker._task is None
        assert tracker.redis is None

    @pytest.mark.asyncio
    async def test_initialize_disabled_no_task(self, tracker):
        """Bei enabled=False wird kein Hintergrund-Task gestartet."""
        tracker.enabled = False
        redis_mock = AsyncMock()
        await tracker.initialize(redis_client=redis_mock)
        assert tracker._task is None

    @pytest.mark.asyncio
    async def test_initialize_starts_reminder_loop(self, tracker):
        """Bei enabled=True und Redis wird der Reminder-Loop gestartet."""
        tracker.enabled = True
        redis_mock = AsyncMock()

        with patch.object(tracker, "_reminder_loop", new_callable=AsyncMock):
            await tracker.initialize(redis_client=redis_mock)
            assert tracker._running is True
            assert tracker._task is not None
            # Aufraaeumen
            await tracker.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, tracker):
        """stop() setzt _running auf False und cancelt den Task."""
        tracker._running = True

        # Einen echten laufenden Task erstellen der auf cancel wartet
        async def hang_forever():
            await asyncio.sleep(3600)

        task = asyncio.create_task(hang_forever())
        tracker._task = task

        await tracker.stop()
        assert tracker._running is False
        assert task.cancelled()

    def test_set_notify_callback(self, tracker):
        """set_notify_callback setzt den Callback korrekt."""
        cb = MagicMock()
        tracker.set_notify_callback(cb)
        assert tracker._notify_callback is cb


class TestReminderLoop:
    """Tests fuer _reminder_loop() — Hintergrund-Erinnerungen."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        t.redis = AsyncMock()
        t._running = True
        t.check_interval = 0.01  # Sehr kurz fuer Tests
        return t

    @pytest.mark.asyncio
    async def test_reminder_loop_calls_callback(self, tracker):
        """Loop ruft Notify-Callback fuer faellige Intents auf."""
        callback = MagicMock()
        tracker.set_notify_callback(callback)

        due_intent = {
            "intent": "Besuch",
            "reminder_text": "Deine Eltern kommen morgen!",
            "time_until_hours": 6.0,
            "intent_id": "intent_cb",
        }

        call_count = 0

        async def mock_get_due():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [due_intent]
            # Stop nach erstem Durchlauf
            tracker._running = False
            return []

        with patch.object(tracker, "get_due_intents", side_effect=mock_get_due):
            await tracker._reminder_loop()

        callback.assert_called_once()
        call_data = callback.call_args[0][0]
        assert call_data["type"] == "intent_reminder"
        assert call_data["text"] == "Deine Eltern kommen morgen!"

    @pytest.mark.asyncio
    async def test_reminder_loop_generates_default_text(self, tracker):
        """Wenn kein reminder_text vorhanden, wird ein Default generiert."""
        callback = MagicMock()
        tracker.set_notify_callback(callback)

        due_intent = {
            "intent": "Arzttermin",
            "reminder_text": "",
            "time_until_hours": 3.5,
            "intent_id": "intent_def",
        }

        call_count = 0

        async def mock_get_due():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [due_intent]
            tracker._running = False
            return []

        with patch.object(tracker, "get_due_intents", side_effect=mock_get_due):
            await tracker._reminder_loop()

        call_data = callback.call_args[0][0]
        assert "Arzttermin" in call_data["text"]
        assert "3.5" in call_data["text"]

    @pytest.mark.asyncio
    async def test_reminder_loop_handles_async_callback(self, tracker):
        """Loop kann auch einen async Callback aufrufen."""
        callback = AsyncMock()
        tracker.set_notify_callback(callback)

        due_intent = {
            "intent": "Test",
            "reminder_text": "Erinnerung",
            "time_until_hours": 1.0,
            "intent_id": "intent_async",
        }

        call_count = 0

        async def mock_get_due():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [due_intent]
            tracker._running = False
            return []

        with patch.object(tracker, "get_due_intents", side_effect=mock_get_due):
            await tracker._reminder_loop()

        callback.assert_called_once()


class TestParseRelativeDateEdgeCases:
    """Weitere Edge-Cases fuer parse_relative_date()."""

    def test_guten_morgen_not_matched_as_morgen(self):
        """'guten morgen' soll nicht als 'morgen' interpretiert werden."""
        ref = datetime(2026, 3, 20, 8, 0, 0)
        result = parse_relative_date("guten morgen", ref)
        assert result is None

    def test_heute_in_sentence(self):
        """'heute' innerhalb eines Satzes wird erkannt."""
        ref = datetime(2026, 3, 20, 10, 0, 0)
        result = parse_relative_date("ich komme heute vorbei", ref)
        assert result == "2026-03-20"

    def test_umlaut_naechste_woche(self):
        """Umlaute (nächste) werden korrekt normalisiert."""
        ref = datetime(2026, 3, 20, 10, 0, 0)  # Freitag
        result = parse_relative_date("nächste Woche", ref)
        assert result == "2026-03-27"

    def test_in_1_tag(self):
        """'in 1 Tag' = morgen."""
        ref = datetime(2026, 3, 20, 10, 0, 0)
        result = parse_relative_date("in 1 Tag", ref)
        assert result == "2026-03-21"

    def test_same_weekday_jumps_to_next_week(self):
        """Wenn der genannte Wochentag der heutige ist, springt es zur naechsten Woche."""
        ref = datetime(2026, 3, 20, 10, 0, 0)  # Freitag
        result = parse_relative_date("am Freitag", ref)
        assert result == "2026-03-27"  # Naechster Freitag


class TestExtractIntentsAdvanced:
    """Erweiterte Tests fuer extract_intents()."""

    @pytest.fixture
    def tracker(self):
        ollama = AsyncMock()
        t = IntentTracker(ollama)
        return t

    @pytest.mark.asyncio
    async def test_llm_returns_valid_intents(self, tracker):
        """LLM-Antwort mit gueltigem Intent wird korrekt geparst."""
        tracker.ollama.chat.return_value = {
            "message": {
                "content": json.dumps(
                    [
                        {
                            "intent": "Elternbesuch",
                            "deadline": "2026-03-25",
                            "person": "Eltern",
                            "suggested_actions": ["Gaestemodus vorbereiten"],
                            "reminder_text": "Deine Eltern kommen morgen.",
                        }
                    ]
                ),
            },
        }
        result = await tracker.extract_intents(
            "Meine Eltern kommen morgen zu Besuch und bleiben bis Sonntag",
            person="Max",
        )
        assert len(result) == 1
        assert result[0]["intent"] == "Elternbesuch"

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(self, tracker):
        """Bei LLM-Fehler wird leere Liste zurueckgegeben."""
        tracker.ollama.chat.side_effect = Exception("Ollama timeout")
        result = await tracker.extract_intents(
            "Ich habe morgen einen wichtigen Termin beim Arzt um zehn Uhr"
        )
        assert result == []
