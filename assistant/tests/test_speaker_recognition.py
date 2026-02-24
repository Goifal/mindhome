"""
Tests fuer SpeakerRecognition — Personen-Erkennung.
"""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from assistant.speaker_recognition import SpeakerProfile, SpeakerRecognition


@pytest.fixture
def ha_client():
    return AsyncMock()


@pytest.fixture
def redis_mock():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock()
    r.lpush = AsyncMock()
    r.ltrim = AsyncMock()
    r.lrange = AsyncMock(return_value=[])
    r.delete = AsyncMock()
    r.exists = AsyncMock(return_value=0)
    r.expire = AsyncMock()
    return r


@pytest.fixture
def recognition(ha_client, redis_mock):
    with patch("assistant.speaker_recognition.yaml_config") as mock_cfg:
        mock_cfg.get.return_value = {
            "enabled": True,
            "min_confidence": 0.7,
            "fallback_ask": True,
            "max_profiles": 10,
            "device_mapping": {
                "media_player.kueche": "max",
                "media_player.schlafzimmer": "lisa",
            },
            "doa_mapping": {
                "respeaker_kueche": {
                    "0-90": "max",
                    "270-360": "lisa",
                },
            },
            "doa_tolerance": 30,
        }
        sr = SpeakerRecognition(ha_client)
        sr.redis = redis_mock
        return sr


class TestSpeakerProfile:
    def test_create_profile(self):
        p = SpeakerProfile("Max", "max")
        assert p.name == "Max"
        assert p.person_id == "max"
        assert p.sample_count == 0

    def test_update_voice_stats_first(self):
        p = SpeakerProfile("Max", "max")
        p.update_voice_stats(wpm=130, duration=3.5, volume=0.6)
        assert p.avg_wpm == 130
        assert p.avg_duration == 3.5
        assert p.sample_count == 1

    def test_update_voice_stats_ema(self):
        p = SpeakerProfile("Max", "max")
        p.update_voice_stats(wpm=100, duration=3.0, volume=0.5)
        p.update_voice_stats(wpm=200, duration=5.0, volume=0.7)
        # EMA alpha=0.3: 0.3*200 + 0.7*100 = 130
        assert abs(p.avg_wpm - 130) < 0.01
        assert p.sample_count == 2

    def test_serialization(self):
        p = SpeakerProfile("Lisa", "lisa")
        p.update_voice_stats(wpm=120, duration=4.0, volume=0.5)
        d = p.to_dict()
        p2 = SpeakerProfile.from_dict(d)
        assert p2.name == "Lisa"
        assert p2.avg_wpm == 120
        assert p2.sample_count == 1


class TestIdentification:
    @pytest.mark.asyncio
    async def test_device_mapping(self, recognition):
        # Profile anlegen damit Name verfuegbar ist
        recognition._profiles["max"] = SpeakerProfile("Max", "max")
        result = await recognition.identify(device_id="media_player.kueche")
        assert result["person"] == "Max"
        assert result["confidence"] == 0.95
        assert result["method"] == "device_mapping"

    @pytest.mark.asyncio
    async def test_unknown_device(self, recognition):
        result = await recognition.identify(device_id="media_player.unbekannt")
        assert result["method"] == "unknown"
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_disabled(self, recognition):
        recognition.enabled = False
        result = await recognition.identify()
        assert result["method"] == "disabled"


class TestVoiceMatching:
    def test_matching_with_profiles(self, recognition):
        p = SpeakerProfile("Max", "max")
        for _ in range(5):
            p.update_voice_stats(wpm=130, duration=3.5, volume=0.6)
        recognition._profiles["max"] = p

        p2 = SpeakerProfile("Lisa", "lisa")
        for _ in range(5):
            p2.update_voice_stats(wpm=100, duration=5.0, volume=0.4)
        recognition._profiles["lisa"] = p2

        result = recognition._match_voice_features({"wpm": 128, "duration": 3.3, "volume": 0.58})
        assert result is not None
        assert result["name"] == "Max"  # Naeher an Max's Profil

    def test_no_match_with_few_samples(self, recognition):
        p = SpeakerProfile("Max", "max")
        p.update_voice_stats(wpm=130)  # Nur 1 Sample
        recognition._profiles["max"] = p
        result = recognition._match_voice_features({"wpm": 130})
        assert result is None  # Braucht min 3 Samples

    def test_volume_matching(self, recognition):
        """Lautstaerke wird jetzt auch beruecksichtigt."""
        p = SpeakerProfile("Max", "max")
        for _ in range(5):
            p.update_voice_stats(wpm=130, duration=3.5, volume=0.8)
        recognition._profiles["max"] = p

        result = recognition._match_voice_features({"volume": 0.78})
        assert result is not None
        assert result["name"] == "Max"


class TestEnrollment:
    @pytest.mark.asyncio
    async def test_enroll_new_profile(self, recognition, redis_mock):
        result = await recognition.enroll("tom", "Tom", audio_features={"wpm": 110})
        assert result is True
        assert "tom" in recognition._profiles
        assert recognition._profiles["tom"].avg_wpm == 110

    @pytest.mark.asyncio
    async def test_enroll_with_device(self, recognition, redis_mock):
        await recognition.enroll("tom", "Tom", device_id="media_player.buero")
        assert "media_player.buero" in recognition._device_mapping
        assert recognition._device_mapping["media_player.buero"] == "tom"

    @pytest.mark.asyncio
    async def test_max_profiles_limit(self, recognition, redis_mock):
        recognition.max_profiles = 2
        await recognition.enroll("a", "A")
        await recognition.enroll("b", "B")
        result = await recognition.enroll("c", "C")
        assert result is False  # Limit erreicht


class TestHistory:
    @pytest.mark.asyncio
    async def test_log_identification(self, recognition, redis_mock):
        await recognition.log_identification("max", "device_mapping", 0.95)
        redis_mock.lpush.assert_called_once()
        redis_mock.ltrim.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_history(self, recognition, redis_mock):
        entry = json.dumps({"person": "max", "method": "device", "confidence": 0.95, "time": 1000})
        redis_mock.lrange = AsyncMock(return_value=[entry])
        history = await recognition.get_identification_history(limit=5)
        assert len(history) == 1
        assert history[0]["person"] == "max"


class TestDoA:
    """Tests fuer Direction of Arrival Erkennung."""

    def test_doa_match_in_range(self, recognition):
        recognition._profiles["max"] = SpeakerProfile("Max", "max")
        result = recognition._identify_by_doa("respeaker_kueche", 45.0)
        assert result is not None
        assert result["person"] == "Max"
        assert result["confidence"] == 0.85

    def test_doa_match_second_range(self, recognition):
        recognition._profiles["lisa"] = SpeakerProfile("Lisa", "lisa")
        result = recognition._identify_by_doa("respeaker_kueche", 300.0)
        assert result is not None
        assert result["person"] == "Lisa"

    def test_doa_no_match_gap(self, recognition):
        """Winkel in keinem Bereich → kein Match."""
        result = recognition._identify_by_doa("respeaker_kueche", 180.0)
        assert result is None

    def test_doa_unknown_device(self, recognition):
        result = recognition._identify_by_doa("unknown_device", 45.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_doa_in_identify_chain(self, recognition):
        """DoA wird in identify() aufgerufen wenn doa_angle vorhanden."""
        recognition._profiles["max"] = SpeakerProfile("Max", "max")
        result = await recognition.identify(
            device_id="respeaker_kueche",
            audio_metadata={"doa_angle": 45.0},
        )
        # Kein Device-Mapping fuer respeaker_kueche → DoA greift
        assert result["method"] == "doa"
        assert result["person"] == "Max"
        assert result["confidence"] == 0.85


class TestVoiceEmbedding:
    """Tests fuer Voice Embedding Matching."""

    @pytest.mark.asyncio
    async def test_identify_by_embedding_match(self, recognition, redis_mock):
        """Cosinus-Aehnlichkeit findet aehnliches Embedding."""
        recognition._profiles["max"] = SpeakerProfile("Max", "max")
        # Stored embedding (192-dim simuliert als 4-dim)
        stored = [0.5, 0.3, 0.8, 0.1]
        redis_mock.get = AsyncMock(return_value=json.dumps(stored))

        # Sehr aehnliches Embedding
        query = [0.51, 0.29, 0.79, 0.11]
        result = await recognition.identify_by_embedding(query)
        assert result is not None
        assert result["person"] == "Max"
        assert result["method"] == "voice_embedding"
        assert result["confidence"] > 0.9

    @pytest.mark.asyncio
    async def test_identify_by_embedding_no_match(self, recognition, redis_mock):
        """Kein gespeichertes Embedding → kein Match."""
        recognition._profiles["max"] = SpeakerProfile("Max", "max")
        redis_mock.get = AsyncMock(return_value=None)
        result = await recognition.identify_by_embedding([0.5, 0.3])
        assert result is None

    @pytest.mark.asyncio
    async def test_store_embedding_new(self, recognition, redis_mock):
        """Neues Embedding speichern."""
        recognition._profiles["max"] = SpeakerProfile("Max", "max")
        redis_mock.get = AsyncMock(return_value=None)
        result = await recognition.store_embedding("max", [0.5, 0.3, 0.8])
        assert result is True
        redis_mock.set.assert_called()

    @pytest.mark.asyncio
    async def test_store_embedding_ema_merge(self, recognition, redis_mock):
        """EMA-Verschmelzung mit bestehendem Embedding."""
        recognition._profiles["max"] = SpeakerProfile("Max", "max")
        stored = [1.0, 0.0]
        redis_mock.get = AsyncMock(return_value=json.dumps(stored))

        await recognition.store_embedding("max", [0.0, 1.0])
        # EMA alpha=0.3: merged = [0.3*0.0 + 0.7*1.0, 0.3*1.0 + 0.7*0.0] = [0.7, 0.3]
        call_args = redis_mock.set.call_args_list
        # Finde den set-Aufruf fuer das Embedding (nicht fuer Profile)
        emb_call = [c for c in call_args if "embedding" in str(c)]
        assert len(emb_call) > 0


class TestFallbackAsk:
    """Tests fuer 'Wer bist du?' Rueckfrage."""

    @pytest.mark.asyncio
    async def test_start_fallback_ask_two_persons(self, recognition, redis_mock):
        """Rueckfrage mit 2 Personen generiert natuerliche Frage."""
        recognition.ha = AsyncMock()
        recognition.ha.get_states = AsyncMock(return_value=[
            {"entity_id": "person.max", "state": "home",
             "attributes": {"friendly_name": "Max"}},
            {"entity_id": "person.lisa", "state": "home",
             "attributes": {"friendly_name": "Lisa"}},
        ])
        question = await recognition.start_fallback_ask(
            guessed_person="max", original_text="Mach das Licht an",
        )
        assert "Max" in question
        assert "Lisa" in question
        redis_mock.set.assert_called()

    @pytest.mark.asyncio
    async def test_resolve_fallback_simple_name(self, recognition, redis_mock):
        """Einfache Namensantwort wird aufgeloest."""
        pending = json.dumps({
            "original_text": "Mach das Licht an",
            "guessed_person": None,
            "persons": ["Max", "Lisa"],
            "time": time.time(),
        })
        redis_mock.get = AsyncMock(return_value=pending)
        result = await recognition.resolve_fallback_answer("Max")
        assert result is not None
        assert result["person"] == "Max"
        assert result["original_text"] == "Mach das Licht an"

    @pytest.mark.asyncio
    async def test_resolve_fallback_with_prefix(self, recognition, redis_mock):
        """'Ich bin Lisa' wird korrekt aufgeloest."""
        pending = json.dumps({
            "original_text": "",
            "persons": ["Max", "Lisa"],
            "time": time.time(),
        })
        redis_mock.get = AsyncMock(return_value=pending)
        result = await recognition.resolve_fallback_answer("Ich bin Lisa")
        assert result is not None
        assert result["person"] == "Lisa"

    @pytest.mark.asyncio
    async def test_resolve_fallback_unknown_name(self, recognition, redis_mock):
        """Unbekannter Name → None."""
        pending = json.dumps({
            "original_text": "",
            "persons": ["Max", "Lisa"],
            "time": time.time(),
        })
        redis_mock.get = AsyncMock(return_value=pending)
        result = await recognition.resolve_fallback_answer("Tom")
        assert result is None

    @pytest.mark.asyncio
    async def test_has_pending_ask(self, recognition, redis_mock):
        """Pending-State pruefen."""
        redis_mock.exists = AsyncMock(return_value=1)
        assert await recognition.has_pending_ask() is True
        redis_mock.exists = AsyncMock(return_value=0)
        assert await recognition.has_pending_ask() is False

    @pytest.mark.asyncio
    async def test_no_pending_without_redis(self, recognition):
        """Ohne Redis kein Pending."""
        recognition.redis = None
        assert await recognition.has_pending_ask() is False


class TestWyomingEmbedding:
    """Tests fuer Wyoming-Embedding aus Redis."""

    @pytest.mark.asyncio
    async def test_get_wyoming_embedding_found(self, recognition, redis_mock):
        """Wyoming-Embedding aus Redis wird gelesen und konsumiert."""
        embedding = [0.1, 0.2, 0.3, 0.4]
        redis_mock.get = AsyncMock(return_value=json.dumps(embedding))
        result = await recognition._get_wyoming_embedding()
        assert result == embedding
        redis_mock.delete.assert_called_with("mha:speaker:latest_embedding")

    @pytest.mark.asyncio
    async def test_get_wyoming_embedding_not_found(self, recognition, redis_mock):
        """Kein Wyoming-Embedding → None."""
        redis_mock.get = AsyncMock(return_value=None)
        result = await recognition._get_wyoming_embedding()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_wyoming_embedding_no_redis(self, recognition):
        """Ohne Redis → None."""
        recognition.redis = None
        result = await recognition._get_wyoming_embedding()
        assert result is None

    @pytest.mark.asyncio
    async def test_identify_uses_wyoming_embedding(self, recognition, redis_mock):
        """identify() nutzt Wyoming-Embedding wenn vorhanden."""
        recognition._profiles["max"] = SpeakerProfile("Max", "max")
        # Stored profile embedding
        stored = [0.5, 0.3, 0.8, 0.1]

        # Redis gibt zuerst Wyoming-Embedding, dann Profil-Embedding zurueck
        call_count = 0
        async def mock_get(key):
            nonlocal call_count
            call_count += 1
            if key == "mha:speaker:latest_embedding":
                return json.dumps([0.51, 0.29, 0.79, 0.11])
            elif "embedding:max" in key:
                return json.dumps(stored)
            return None
        redis_mock.get = AsyncMock(side_effect=mock_get)

        result = await recognition.identify()
        assert result["method"] == "voice_embedding"
        assert result["person"] == "Max"


class TestHealthStatus:
    def test_health_status_active(self, recognition):
        status = recognition.health_status()
        assert "active" in status
        assert "profiles" in status
        assert "devices" in status
        assert "embeddings" in status

    def test_health_status_disabled(self, recognition):
        recognition.enabled = False
        assert recognition.health_status() == "disabled"
