"""
Tests fuer CoreIdentity — Unveraenderliche JARVIS-Identitaetskonstanten.

Testet:
- Konstanten-Werte
- build_identity_block() Formatierung
- IDENTITY_BLOCK Inhalt
"""

from assistant.core_identity import (
    NAME, FULL_NAME, ROLE,
    VALUES, BOUNDARIES, RELATIONSHIP, EMOTIONAL_RANGE,
    build_identity_block, IDENTITY_BLOCK,
)


class TestCoreConstants:

    def test_name(self):
        assert NAME == "J.A.R.V.I.S."

    def test_full_name(self):
        assert "Intelligent System" in FULL_NAME

    def test_role_defined(self):
        assert "Butler" in ROLE

    def test_values_non_empty(self):
        assert len(VALUES) >= 4

    def test_boundaries_non_empty(self):
        assert len(BOUNDARIES) >= 4

    def test_security_in_boundaries(self):
        assert any("Sicherheit" in b for b in BOUNDARIES)

    def test_relationship_defined(self):
        assert len(RELATIONSHIP) >= 3

    def test_emotional_range_defined(self):
        assert len(EMOTIONAL_RANGE) >= 4


class TestBuildIdentityBlock:

    def test_contains_name(self):
        block = build_identity_block()
        assert NAME in block

    def test_contains_role(self):
        block = build_identity_block()
        assert ROLE in block

    def test_contains_all_boundaries(self):
        block = build_identity_block()
        for b in BOUNDARIES:
            assert b in block

    def test_contains_kern_identitaet_header(self):
        block = build_identity_block()
        assert "KERN-IDENTITAET" in block

    def test_prebuilt_block_matches(self):
        """Vorgebauter Block muss identisch zum dynamisch erzeugten sein."""
        assert IDENTITY_BLOCK == build_identity_block()
