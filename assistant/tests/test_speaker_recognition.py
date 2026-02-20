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
