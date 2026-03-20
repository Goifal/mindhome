"""
Tests fuer constants.py — Sanity-Checks fuer zentrale Konstanten.

Stellt sicher dass Timeouts, Limits und Schwellwerte plausibel sind.
"""

from assistant.constants import (
    # Timeouts
    LLM_TIMEOUT_FAST, LLM_TIMEOUT_SMART, LLM_TIMEOUT_DEEP,
    HA_SESSION_TIMEOUT, HA_RETRY_MAX,
    BRAIN_PROCESS_TIMEOUT,
    # Redis TTLs
    REDIS_WORKING_MEMORY_MAX_ITEMS, REDIS_CONVERSATION_ARCHIVE_TTL,
    REDIS_SECURITY_CONFIRM_TTL,
    # Limits
    ERROR_BUFFER_MAX_SIZE, MAX_NOTIFICATION_LENGTH,
    # Health
    CO2_WARN_PPM, CO2_CRITICAL_PPM,
    HUMIDITY_LOW_PERCENT, HUMIDITY_HIGH_PERCENT,
    TEMP_LOW_CELSIUS, TEMP_HIGH_CELSIUS,
    # Trust
    TRUST_OWNER, TRUST_MEMBER, TRUST_GUEST,
    # Climate
    CLIMATE_TEMP_MIN, CLIMATE_TEMP_MAX,
)


class TestTimeoutSanity:

    def test_llm_timeout_ordering(self):
        """Fast < Smart < Deep Timeouts."""
        assert LLM_TIMEOUT_FAST < LLM_TIMEOUT_SMART <= LLM_TIMEOUT_DEEP

    def test_llm_timeout_reasonable(self):
        assert LLM_TIMEOUT_FAST >= 10
        assert LLM_TIMEOUT_DEEP <= 300

    def test_ha_timeout_positive(self):
        assert HA_SESSION_TIMEOUT > 0

    def test_ha_retry_reasonable(self):
        assert 1 <= HA_RETRY_MAX <= 10

    def test_brain_timeout_positive(self):
        assert BRAIN_PROCESS_TIMEOUT > 0


class TestRedisLimits:

    def test_working_memory_items(self):
        assert 10 <= REDIS_WORKING_MEMORY_MAX_ITEMS <= 200

    def test_conversation_archive_ttl(self):
        """30 Tage in Sekunden."""
        assert REDIS_CONVERSATION_ARCHIVE_TTL == 30 * 86400

    def test_security_confirm_ttl(self):
        """Security Confirmation: kurzer TTL (< 10 Min)."""
        assert REDIS_SECURITY_CONFIRM_TTL <= 600


class TestHealthThresholds:

    def test_co2_warn_below_critical(self):
        assert CO2_WARN_PPM < CO2_CRITICAL_PPM

    def test_co2_reasonable_range(self):
        assert 400 <= CO2_WARN_PPM <= 1500
        assert 800 <= CO2_CRITICAL_PPM <= 2500

    def test_humidity_range(self):
        assert HUMIDITY_LOW_PERCENT < HUMIDITY_HIGH_PERCENT
        assert 20 <= HUMIDITY_LOW_PERCENT <= 40
        assert 60 <= HUMIDITY_HIGH_PERCENT <= 80

    def test_temperature_range(self):
        assert TEMP_LOW_CELSIUS < TEMP_HIGH_CELSIUS
        assert 10 <= TEMP_LOW_CELSIUS <= 20
        assert 25 <= TEMP_HIGH_CELSIUS <= 35


class TestTrustLevels:

    def test_guest_lowest(self):
        assert TRUST_GUEST < TRUST_MEMBER < TRUST_OWNER

    def test_owner_positive(self):
        assert TRUST_OWNER > 0


class TestClimateConstants:

    def test_temp_range(self):
        assert CLIMATE_TEMP_MIN < CLIMATE_TEMP_MAX
        assert CLIMATE_TEMP_MIN >= 0
        assert CLIMATE_TEMP_MAX <= 50


class TestBufferSizes:

    def test_error_buffer_positive(self):
        assert ERROR_BUFFER_MAX_SIZE > 0

    def test_notification_length_positive(self):
        assert MAX_NOTIFICATION_LENGTH > 0
        assert MAX_NOTIFICATION_LENGTH <= 1000
