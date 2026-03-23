"""Tests fuer FamilyManager - Familien-Profile."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant.family_manager import FamilyManager


@pytest.fixture
def ha_mock():
    return AsyncMock()


@pytest.fixture
def redis_mock():
    mock = AsyncMock()
    mock.hset = AsyncMock()
    mock.sadd = AsyncMock()
    mock.srem = AsyncMock()
    mock.delete = AsyncMock(return_value=1)
    mock.exists = AsyncMock(return_value=0)
    mock.smembers = AsyncMock(return_value=set())
    mock.hgetall = AsyncMock(return_value={})

    pipe = MagicMock()
    pipe.hgetall = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    mock.pipeline = MagicMock(return_value=pipe)

    return mock


@pytest.fixture
def family_mgr(ha_mock, redis_mock):
    fm = FamilyManager(ha_mock)
    fm.redis = redis_mock
    return fm


@pytest.mark.asyncio
async def test_add_member(family_mgr, redis_mock):
    result = await family_mgr.add_member(
        name="Lisa",
        relationship="partner",
        birth_year=1990,
        interests="Yoga, Kochen",
    )
    assert result["success"] is True
    assert "Lisa" in result["message"]
    redis_mock.hset.assert_called()
    redis_mock.sadd.assert_called()


@pytest.mark.asyncio
async def test_add_member_empty_name(family_mgr):
    result = await family_mgr.add_member(name="")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_add_member_invalid_relationship(family_mgr, redis_mock):
    result = await family_mgr.add_member(
        name="Max",
        relationship="invalid_type",
    )
    assert result["success"] is True  # Fallback auf "other"


@pytest.mark.asyncio
async def test_get_member_not_found(family_mgr, redis_mock):
    redis_mock.hgetall = AsyncMock(return_value={})
    member = await family_mgr.get_member("unbekannt")
    assert member is None


@pytest.mark.asyncio
async def test_get_member_found(family_mgr, redis_mock):
    redis_mock.hgetall = AsyncMock(
        return_value={
            "name": "Lisa",
            "name_key": "lisa",
            "relationship": "partner",
            "birth_year": "1990",
            "interests": "Yoga",
        }
    )
    member = await family_mgr.get_member("Lisa")
    assert member is not None
    assert member["name"] == "Lisa"
    assert member["relationship"] == "partner"


@pytest.mark.asyncio
async def test_remove_member(family_mgr, redis_mock):
    result = await family_mgr.remove_member("Lisa")
    assert result["success"] is True
    redis_mock.delete.assert_called()


@pytest.mark.asyncio
async def test_remove_member_not_found(family_mgr, redis_mock):
    redis_mock.delete = AsyncMock(return_value=0)
    result = await family_mgr.remove_member("Unbekannt")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_get_age_group_adult(family_mgr, redis_mock):
    redis_mock.hgetall = AsyncMock(
        return_value={
            "name": "Lisa",
            "birth_year": "1990",
        }
    )
    group = await family_mgr.get_age_group("Lisa")
    assert group == "adult"


@pytest.mark.asyncio
async def test_get_age_group_child(family_mgr, redis_mock):
    redis_mock.hgetall = AsyncMock(
        return_value={
            "name": "Max Jr",
            "birth_year": "2020",
        }
    )
    group = await family_mgr.get_age_group("Max Jr")
    assert group == "child"


@pytest.mark.asyncio
async def test_get_age_group_no_profile(family_mgr, redis_mock):
    redis_mock.hgetall = AsyncMock(return_value={})
    group = await family_mgr.get_age_group("ghost")
    assert group == "adult"


@pytest.mark.asyncio
async def test_communication_style_child(family_mgr, redis_mock):
    redis_mock.hgetall = AsyncMock(
        return_value={
            "name": "Max Jr",
            "birth_year": "2020",
        }
    )
    style = await family_mgr.get_communication_style("Max Jr")
    assert style["formality"] == "informal"
    assert style["vocabulary"] == "simple"


@pytest.mark.asyncio
async def test_send_family_message_no_callback(family_mgr):
    result = await family_mgr.send_family_message(message="Test")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_get_all_members_empty(family_mgr, redis_mock):
    members = await family_mgr.get_all_members()
    assert members == []


def test_context_hints():
    fm = FamilyManager(AsyncMock())
    hints = fm.get_context_hints()
    assert len(hints) > 0
