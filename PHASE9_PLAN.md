# MindHome Phase 9 — Implementierungsplan
# "Jarvis Stimme & Akustik" (6 Features)

> **Stand:** 2026-02-17
> **Version:** v0.9.8 → v1.0.0
> **Basis:** Assistant v0.9.8 (Phase 8 fertig)
> **Status:** ALLE 6 FEATURES IMPLEMENTIERT

---

## Strategie

Phase 9 wird in **3 Batches** mit **~5 Commits** implementiert:

1. **TTS-Erweiterung** (SSML Enhancement, Auto-Volume)
2. **Sound & Narration** (Sound Design, Narration Mode)
3. **Stimm-Analyse** (Voice Emotion, Speaker Recognition)

### Commit-Plan (~5 Commits)

| # | Commit | Batch | Features |
|---|--------|-------|----------|
| 1 | `chore: Bump to v0.9.9 + Phase 9 plan` | 0 | Version bump |
| 2 | `feat(tts): Add TTS enhancer with SSML + auto-volume` | 1 | #9.1, #9.3 |
| 3 | `feat(sound): Add sound design + narration mode` | 2 | #9.2, #9.4 |
| 4 | `feat(voice): Add voice analysis + speaker recognition` | 3 | #9.5, #9.6 |
| 5 | `feat: Integrate Phase 9 + bump to v1.0.0` | 3 | Integration |

---

## Batch 1: TTS-Erweiterung (Commit 2)

### Feature 9.1: SSML Enhancement

**Neue Datei:** `assistant/tts_enhancer.py`

- `TTSEnhancer` — Generiert SSML-Tags basierend auf Nachrichtentyp
- Pausen vor wichtigen Infos (300ms)
- Langsamer bei Warnungen (85% Speed)
- Schneller bei Routine-Bestaetigungen (105%)
- Betonung bei Fragen und wichtigen Woertern
- Nachrichtentypen: confirmation, warning, greeting, briefing, question, casual

### Feature 9.3: Auto-Volume (Fluestermodus)

**Datei:** `assistant/activity.py` — Neue Volume-Levels

- Volume-Mapping pro Aktivitaet + Tageszeit:
  - Tag normal: 80%
  - Abend (>22:00): 50%
  - Nacht (>0:00): 30%
  - Jemand schlaeft: 20%
  - Notfall: 100%
- `get_volume_level(activity, urgency)` — Bestimmt Lautstaerke
- "Psst" / "Leise" → Fluestermodus bis Widerruf

**Datei:** `assistant/function_calling.py` — TTS mit Volume

- `send_notification()` mit Volume-Parameter
- Volume wird via `media_player.volume_set` vor TTS gesetzt

---

## Batch 2: Sound & Narration (Commit 3)

### Feature 9.2: Sound Design

**Neue Datei:** `assistant/sound_manager.py`

- `SoundManager` — Verwaltet akustische Identitaet
- Sound-Events:
  - `listening` — Soft chime (Jarvis hoert zu)
  - `confirmed` — Short ping (Befehl bestaetigt)
  - `warning` — Two-tone alert
  - `alarm` — Urgent tone
  - `doorbell` — Soft bell
  - `greeting` — Welcome chime
- Sounds via HA Media Player abspielen
- Lautstaerke passt sich an (Nacht = leiser)
- Sound-Konfiguration in settings.yaml

### Feature 9.4: Narration Mode

**Datei:** `assistant/action_planner.py` — Sequentielle Transitions

- Transition-Dauern zwischen Schritten (konfigurierbar)
- Licht-Aenderungen: `transition: 5` (5 Sek. dimmen)
- Narration-Texte zwischen Schritten
- `play_narration_step()` — Beschreibt was gerade passiert

**Datei:** `assistant/function_calling.py` — Transition-Parameter

- `set_light()` mit `transition`-Parameter (HA unterstuetzt)
- Szenen mit Transitions statt abrupten Wechseln

---

## Batch 3: Stimm-Analyse (Commit 4)

### Feature 9.5: Voice Emotion Detection

**Datei:** `assistant/mood_detector.py` — Erweiterte Signale

- Neue Methode `analyze_voice_metadata(metadata)`:
  - Sprechgeschwindigkeit (WPM) → schnell = gestresst
  - Satzlaenge → kurz = gestresst/muede
  - Lautstaerke → laut = aufgeregt, leise = muede
- Whisper STT Metadaten nutzen (wenn verfuegbar)
- Fallback: Text-basierte Heuristiken bleiben

### Feature 9.6: Speaker Recognition

**Neue Datei:** `assistant/speaker_recognition.py`

- `SpeakerRecognition` — Personen-Erkennung per Stimme
- Enrollment: Voice-Print speichern (30s Sprache)
- Erkennung via Confidence-Score
- Fallback: "Wer spricht?" bei niedriger Confidence
- Redis-basiertes Voice-Print-Storage
- API-Endpoints fuer Enrollment + Identifikation
- **Hinweis:** Optionales Feature, braucht pyannote-audio

---

## Neue/Geaenderte Dateien

### Neue Dateien:
| Datei | Beschreibung |
|-------|-------------|
| `assistant/tts_enhancer.py` | SSML-Generierung + Nachrichtentyp-Erkennung |
| `assistant/sound_manager.py` | Akustische Identitaet + Event-Sounds |
| `assistant/speaker_recognition.py` | Personen-Erkennung per Stimme |

### Geaenderte Dateien:
| Datei | Aenderung |
|-------|---------
| `config/settings.yaml` | Version bump, TTS/Sound/Voice-Config |
| `assistant/activity.py` | Volume-Levels pro Aktivitaet |
| `assistant/mood_detector.py` | Voice-Metadata-Integration |
| `assistant/action_planner.py` | Narration-Mode + Transitions |
| `assistant/function_calling.py` | transition-Param, play_sound, Volume-TTS |
| `assistant/brain.py` | TTS-Enhancer + SoundManager + SpeakerRecog Integration |
| `assistant/main.py` | Neue API-Endpoints (TTS, Speaker, Sounds) |
| `assistant/websocket.py` | Audio-Metadata Events |
