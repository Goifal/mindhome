"""
Multi-Room Audio Sync — Speaker-Gruppen, synchrone Wiedergabe, Zonen.

Funktionen:
- Benannte Speaker-Gruppen (z.B. "Erdgeschoss", "Party", "Ueberall")
- Synchrone Wiedergabe ueber mehrere Speaker
- Gruppen-Lautstaerke (einheitlich oder pro Speaker)
- HA media_player.join / unjoin fuer native Gruppierung (Sonos, Cast)
- Fallback: Paralleles play_media auf alle Gruppen-Speaker

Gespeichert in Redis fuer Persistenz.
"""

import asyncio
import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from .config import yaml_config
from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)

# Redis Keys
_KEY_GROUPS = "mha:audio:groups"          # Hash: group_name -> JSON
_KEY_ACTIVE_GROUP = "mha:audio:active"    # String: aktuell aktive Gruppe

_DEFAULT_MAX_GROUPS = 10


class MultiRoomAudio:
    """Verwaltet Speaker-Gruppen und synchrone Multi-Room-Wiedergabe."""

    def __init__(self, ha_client: HomeAssistantClient):
        self.ha = ha_client
        self.redis: Optional[aioredis.Redis] = None
        cfg = yaml_config.get("multi_room_audio", {})
        self.enabled = cfg.get("enabled", True)
        self.max_groups = cfg.get("max_groups", _DEFAULT_MAX_GROUPS)
        self.default_volume = cfg.get("default_volume", 40)
        # Native Gruppierung (Sonos/Cast) vs. paralleles play_media
        self.use_native_grouping = cfg.get("use_native_grouping", False)

    async def initialize(self, redis_client: Optional[aioredis.Redis] = None):
        """Initialisiert mit Redis-Verbindung."""
        self.redis = redis_client
        logger.info("MultiRoomAudio initialisiert (enabled: %s, native_grouping: %s)",
                     self.enabled, self.use_native_grouping)

    # ------------------------------------------------------------------
    # Gruppen-Verwaltung
    # ------------------------------------------------------------------

    async def create_group(self, name: str, speakers: list[str],
                           description: str = "") -> dict:
        """Erstellt eine benannte Speaker-Gruppe.

        Args:
            name: Gruppenname (z.B. "Erdgeschoss", "Party")
            speakers: Liste von media_player Entity-IDs
            description: Optionale Beschreibung
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar."}

        if not speakers:
            return {"success": False, "message": "Keine Speaker angegeben."}

        count = await self.redis.hlen(_KEY_GROUPS)
        if count >= self.max_groups:
            return {"success": False, "message": f"Maximale Gruppenanzahl ({self.max_groups}) erreicht."}

        group = {
            "name": name,
            "speakers": speakers,
            "description": description,
            "volume": self.default_volume,
            "speaker_volumes": {s: self.default_volume for s in speakers},
        }

        try:
            await self.redis.hset(_KEY_GROUPS, name.lower(), json.dumps(group))
            speaker_names = await self._get_speaker_names(speakers)
            logger.info("Audio-Gruppe erstellt: %s (%d Speaker)", name, len(speakers))
            return {
                "success": True,
                "message": f"Gruppe '{name}' erstellt mit {len(speakers)} Speakern: {', '.join(speaker_names)}",
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def delete_group(self, name: str) -> dict:
        """Loescht eine Speaker-Gruppe."""
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar."}

        try:
            removed = await self.redis.hdel(_KEY_GROUPS, name.lower())
            if not removed:
                return {"success": False, "message": f"Gruppe '{name}' nicht gefunden."}
            # Wenn aktive Gruppe geloescht wird, zurücksetzen
            active = await self.redis.get(_KEY_ACTIVE_GROUP)
            if active:
                active_str = active.decode() if isinstance(active, bytes) else active
                if active_str == name.lower():
                    await self.redis.delete(_KEY_ACTIVE_GROUP)
            return {"success": True, "message": f"Gruppe '{name}' geloescht."}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def modify_group(self, name: str, add_speakers: list[str] = None,
                           remove_speakers: list[str] = None) -> dict:
        """Fuegt Speaker hinzu oder entfernt sie aus einer Gruppe."""
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar."}

        group = await self._get_group(name)
        if not group:
            return {"success": False, "message": f"Gruppe '{name}' nicht gefunden."}

        changes = []
        if add_speakers:
            for s in add_speakers:
                if s not in group["speakers"]:
                    group["speakers"].append(s)
                    group["speaker_volumes"][s] = group.get("volume", self.default_volume)
                    changes.append(f"+{s}")
        if remove_speakers:
            for s in remove_speakers:
                if s in group["speakers"]:
                    group["speakers"].remove(s)
                    group["speaker_volumes"].pop(s, None)
                    changes.append(f"-{s}")

        if not changes:
            return {"success": False, "message": "Keine Aenderungen."}

        try:
            await self.redis.hset(_KEY_GROUPS, name.lower(), json.dumps(group))
            return {"success": True, "message": f"Gruppe '{name}' aktualisiert: {', '.join(changes)} ({len(group['speakers'])} Speaker)"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def list_groups(self) -> list[dict]:
        """Gibt alle Speaker-Gruppen zurueck."""
        if not self.redis or not self.enabled:
            return []

        try:
            raw = await self.redis.hgetall(_KEY_GROUPS)
            groups = []
            for val in raw.values():
                val_str = val.decode() if isinstance(val, bytes) else val
                groups.append(json.loads(val_str))
            groups.sort(key=lambda g: g.get("name", ""))
            return groups
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Wiedergabe
    # ------------------------------------------------------------------

    async def play_to_group(self, group_name: str, query: str = "",
                            media_content_id: str = "",
                            media_content_type: str = "music") -> dict:
        """Spielt Musik synchron auf allen Speakern einer Gruppe.

        Args:
            group_name: Name der Gruppe
            query: Suchbegriff (z.B. "Jazz")
            media_content_id: Direkte Content-ID
            media_content_type: Content-Typ (music, playlist, etc.)
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar."}

        group = await self._get_group(group_name)
        if not group:
            return {"success": False, "message": f"Gruppe '{group_name}' nicht gefunden."}

        speakers = group.get("speakers", [])
        if not speakers:
            return {"success": False, "message": "Gruppe hat keine Speaker."}

        content_id = media_content_id or query
        if not content_id:
            return {"success": False, "message": "Kein Inhalt angegeben (query oder media_content_id)."}

        # Aktive Gruppe merken
        await self.redis.set(_KEY_ACTIVE_GROUP, group_name.lower())

        if self.use_native_grouping and len(speakers) > 1:
            return await self._play_native_group(speakers, content_id, media_content_type, group)

        return await self._play_parallel(speakers, content_id, media_content_type, group)

    async def _play_native_group(self, speakers: list[str], content_id: str,
                                 content_type: str, group: dict) -> dict:
        """Nutzt HA media_player.join fuer native Gruppierung."""
        leader = speakers[0]
        followers = speakers[1:]

        try:
            # 1. Lautstaerken setzen
            await self._set_group_volumes(group)

            # 2. Speaker joinen
            if followers:
                await self.ha.call_service("media_player", "join", {
                    "entity_id": leader,
                    "group_members": followers,
                })
                # Kurz warten bis Gruppierung aktiv
                await asyncio.sleep(1)

            # 3. Auf Leader abspielen (Follower bekommen es automatisch)
            await self.ha.call_service("media_player", "play_media", {
                "entity_id": leader,
                "media_content_id": content_id,
                "media_content_type": content_type,
            })

            speaker_names = await self._get_speaker_names(speakers)
            return {
                "success": True,
                "message": f"Spiele '{content_id}' auf Gruppe '{group['name']}' ({len(speakers)} Speaker: {', '.join(speaker_names)})",
            }
        except Exception as e:
            logger.error("Native Gruppierung fehlgeschlagen, Fallback auf parallel: %s", e)
            return await self._play_parallel(speakers, content_id, content_type, group)

    async def _play_parallel(self, speakers: list[str], content_id: str,
                             content_type: str, group: dict) -> dict:
        """Paralleles play_media auf alle Speaker (Fallback)."""
        try:
            await self._set_group_volumes(group)

            # Parallel auf alle Speaker abspielen
            tasks = [
                self.ha.call_service("media_player", "play_media", {
                    "entity_id": speaker,
                    "media_content_id": content_id,
                    "media_content_type": content_type,
                })
                for speaker in speakers
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            succeeded = sum(1 for r in results if not isinstance(r, Exception))
            failed = len(results) - succeeded

            speaker_names = await self._get_speaker_names(speakers)
            msg = f"Spiele '{content_id}' auf {succeeded}/{len(speakers)} Speakern: {', '.join(speaker_names)}"
            if failed:
                msg += f" ({failed} fehlgeschlagen)"

            return {"success": succeeded > 0, "message": msg}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def stop_group(self, group_name: str) -> dict:
        """Stoppt die Wiedergabe auf allen Speakern einer Gruppe."""
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar."}

        group = await self._get_group(group_name)
        if not group:
            return {"success": False, "message": f"Gruppe '{group_name}' nicht gefunden."}

        speakers = group.get("speakers", [])
        try:
            tasks = [
                self.ha.call_service("media_player", "media_stop", {"entity_id": s})
                for s in speakers
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Native Gruppierung auflösen
            if self.use_native_grouping and len(speakers) > 1:
                try:
                    await self.ha.call_service("media_player", "unjoin", {
                        "entity_id": speakers[0],
                    })
                except Exception:
                    pass

            await self.redis.delete(_KEY_ACTIVE_GROUP)
            return {"success": True, "message": f"Wiedergabe auf Gruppe '{group['name']}' gestoppt."}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def pause_group(self, group_name: str) -> dict:
        """Pausiert die Wiedergabe auf allen Speakern einer Gruppe."""
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar."}

        group = await self._get_group(group_name)
        if not group:
            return {"success": False, "message": f"Gruppe '{group_name}' nicht gefunden."}

        try:
            tasks = [
                self.ha.call_service("media_player", "media_pause", {"entity_id": s})
                for s in group.get("speakers", [])
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            return {"success": True, "message": f"Wiedergabe auf Gruppe '{group['name']}' pausiert."}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # Lautstaerke
    # ------------------------------------------------------------------

    async def set_group_volume(self, group_name: str, volume: int,
                               speaker: str = "") -> dict:
        """Setzt die Lautstaerke fuer eine Gruppe oder einen einzelnen Speaker.

        Args:
            group_name: Gruppenname
            volume: Lautstaerke 0-100
            speaker: Optional: Nur diesen Speaker aendern
        """
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar."}

        group = await self._get_group(group_name)
        if not group:
            return {"success": False, "message": f"Gruppe '{group_name}' nicht gefunden."}

        volume = max(0, min(100, volume))

        if speaker:
            # Einzelnen Speaker in der Gruppe aendern
            if speaker not in group.get("speakers", []):
                return {"success": False, "message": f"Speaker '{speaker}' nicht in Gruppe '{group_name}'."}
            group["speaker_volumes"][speaker] = volume
            await self.redis.hset(_KEY_GROUPS, group_name.lower(), json.dumps(group))
            try:
                await self.ha.call_service("media_player", "volume_set", {
                    "entity_id": speaker,
                    "volume_level": volume / 100.0,
                })
            except Exception:
                pass
            return {"success": True, "message": f"Lautstaerke von {speaker} in '{group_name}': {volume}%"}

        # Alle Speaker der Gruppe
        group["volume"] = volume
        for s in group.get("speakers", []):
            group["speaker_volumes"][s] = volume
        await self.redis.hset(_KEY_GROUPS, group_name.lower(), json.dumps(group))
        await self._set_group_volumes(group)
        return {"success": True, "message": f"Lautstaerke der Gruppe '{group_name}': {volume}%"}

    async def _set_group_volumes(self, group: dict):
        """Setzt die Lautstaerke aller Speaker einer Gruppe."""
        tasks = []
        for speaker, vol in group.get("speaker_volumes", {}).items():
            tasks.append(
                self.ha.call_service("media_player", "volume_set", {
                    "entity_id": speaker,
                    "volume_level": vol / 100.0,
                })
            )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def get_group_status(self, group_name: str = "") -> dict:
        """Gibt den Status einer oder aller Gruppen zurueck."""
        if not self.redis or not self.enabled:
            return {"success": False, "message": "Multi-Room Audio nicht verfuegbar."}

        if group_name:
            group = await self._get_group(group_name)
            if not group:
                return {"success": False, "message": f"Gruppe '{group_name}' nicht gefunden."}
            return await self._build_group_status(group)

        groups = await self.list_groups()
        if not groups:
            return {"success": True, "message": "Keine Audio-Gruppen vorhanden."}

        active_raw = await self.redis.get(_KEY_ACTIVE_GROUP)
        active = (active_raw.decode() if isinstance(active_raw, bytes) else active_raw) if active_raw else ""

        lines = [f"Audio-Gruppen ({len(groups)}):"]
        for g in groups:
            is_active = "▶ " if g.get("name", "").lower() == active else "  "
            lines.append(f"{is_active}{g['name']} ({len(g.get('speakers', []))} Speaker, Vol: {g.get('volume', '?')}%)")
            if g.get("description"):
                lines.append(f"    {g['description']}")
        return {"success": True, "message": "\n".join(lines)}

    async def _build_group_status(self, group: dict) -> dict:
        """Detaillierter Status einer einzelnen Gruppe."""
        lines = [f"Gruppe '{group['name']}':"]
        if group.get("description"):
            lines.append(f"  {group['description']}")

        for speaker in group.get("speakers", []):
            vol = group.get("speaker_volumes", {}).get(speaker, "?")
            try:
                state = await self.ha.get_state(speaker)
                if state:
                    s = state.get("state", "unknown")
                    title = state.get("attributes", {}).get("media_title", "")
                    name = state.get("attributes", {}).get("friendly_name", speaker)
                    info = f"  {name}: {s}"
                    if title:
                        info += f" — {title}"
                    info += f" (Vol: {vol}%)"
                    lines.append(info)
                else:
                    lines.append(f"  {speaker}: nicht erreichbar (Vol: {vol}%)")
            except Exception:
                lines.append(f"  {speaker}: Fehler (Vol: {vol}%)")

        return {"success": True, "message": "\n".join(lines)}

    # ------------------------------------------------------------------
    # Presets: Vordefinierte Gruppen aus Konfiguration
    # ------------------------------------------------------------------

    async def load_presets(self):
        """Laedt vordefinierte Gruppen aus settings.yaml."""
        if not self.redis:
            return

        presets = yaml_config.get("multi_room_audio", {}).get("presets", {})
        for name, preset in presets.items():
            speakers = preset.get("speakers", [])
            if not speakers:
                continue
            # Nur laden wenn Gruppe noch nicht existiert
            existing = await self._get_group(name)
            if existing:
                continue
            await self.create_group(
                name=name,
                speakers=speakers,
                description=preset.get("description", ""),
            )
            logger.info("Audio-Preset geladen: %s (%d Speaker)", name, len(speakers))

    # ------------------------------------------------------------------
    # Hilfsmethoden
    # ------------------------------------------------------------------

    async def _get_group(self, name: str) -> Optional[dict]:
        """Holt eine Gruppe aus Redis."""
        if not self.redis:
            return None
        try:
            raw = await self.redis.hget(_KEY_GROUPS, name.lower())
            if not raw:
                return None
            raw_str = raw.decode() if isinstance(raw, bytes) else raw
            return json.loads(raw_str)
        except Exception:
            return None

    async def _get_speaker_names(self, entity_ids: list[str]) -> list[str]:
        """Loest Entity-IDs zu friendly_names auf."""
        names = []
        for eid in entity_ids:
            try:
                state = await self.ha.get_state(eid)
                if state:
                    names.append(state.get("attributes", {}).get("friendly_name", eid))
                else:
                    names.append(eid.replace("media_player.", ""))
            except Exception:
                names.append(eid.replace("media_player.", ""))
        return names

    async def discover_speakers(self) -> list[dict]:
        """Erkennt alle verfuegbaren Speaker im HA-System."""
        try:
            states = await self.ha.get_states()
            speakers = []
            excluded = {"tv", "fernseher", "television", "fire_tv", "apple_tv",
                        "chromecast", "roku", "soundbar", "xbox", "playstation",
                        "receiver", "avr"}

            for state in states:
                eid = state.get("entity_id", "")
                if not eid.startswith("media_player."):
                    continue
                lower_eid = eid.lower()
                if any(ex in lower_eid for ex in excluded):
                    continue
                attrs = state.get("attributes", {})
                if attrs.get("device_class") in ("tv", "receiver"):
                    continue
                speakers.append({
                    "entity_id": eid,
                    "name": attrs.get("friendly_name", eid),
                    "state": state.get("state", "unknown"),
                })

            speakers.sort(key=lambda s: s.get("name", ""))
            return speakers
        except Exception as e:
            logger.debug("Speaker-Erkennung fehlgeschlagen: %s", e)
            return []

    def health_status(self) -> dict:
        """Status fuer Diagnostik."""
        return {
            "enabled": self.enabled,
            "native_grouping": self.use_native_grouping,
            "max_groups": self.max_groups,
            "default_volume": self.default_volume,
        }
