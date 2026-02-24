# Speaker Recognition — Analyse, Status & Roadmap

> **Stand:** 2026-02-24
> **Phase:** 9 / 9.6 (Voice Embeddings vorbereitet)
> **Status:** Deaktiviert in Produktion (`enabled: false`)
> **Geplante Hardware:** ReSpeaker XVF3800 (Hauptraeume) + M5Stack Atom Echo (Nebenraeume) + Sonos (TTS-Ausgabe)

---

## 1. Systemarchitektur

```
PC1 (HAOS)                              PC2 (Assistant + Ollama)
├── HA Assist Pipeline                   ├── /api/assistant/chat (Main Endpoint)
│   ├── Whisper STT (Wyoming)            ├── SpeakerRecognition Engine
│   └── MindHome Conversation Agent      ├── Brain (Context + Person Routing)
├── ESPHome Voice Satellites (Mic-only)  ├── Redis (Profile Storage)
│   ├── ReSpeaker XVF3800 (Hauptraeume)  └── Ollama LLM
│   └── M5Stack Atom Echo (Nebenraeume)
├── Sonos Speakers (TTS-Ausgabe)
└── TTS (Piper → Sonos via announce)
```

### Hardware-Konzept: ReSpeaker + Sonos

```
Pro Raum:
  ┌──────────────────────────┐     ┌─────────────────────┐
  │  ReSpeaker XVF3800       │     │  Sonos Speaker       │
  │  mit Gehaeuse + ESP32-S3 │     │  (z.B. Sonos One)    │
  │  ────────────────────     │     │  ───────────────────  │
  │  • 4-Mic Array (Input)   │     │  • TTS-Ausgabe        │
  │  • Wake Word Detection   │     │  • Musik (ungestoert) │
  │  • KEIN Speaker noetig   │     │  • announce: true     │
  │  • ~65 USD / ~55 EUR     │     │    → duckt Musik,     │
  │                          │     │      spielt Antwort,   │
  │  Seeed Studio p-6628     │     │      Musik geht weiter │
  └──────────────────────────┘     └─────────────────────┘
         ↓ WiFi (ESPHome)                  ↑ LAN/WiFi
         ↓                                 ↑
  ┌──────────────────────────────────────────────────────┐
  │  Home Assistant (PC1 / HAOS)                          │
  │  ├── Assist Pipeline: Wake Word → STT → Intent        │
  │  ├── Piper TTS → generiert Audio-URL                  │
  │  └── on_tts_end → media_player.play_media(Sonos)      │
  └──────────────────────────────────────────────────────┘
```

**Vorteile dieser Trennung:**
- ReSpeaker braucht keinen Speaker-Anschluss → kompakter, guenstiger
- Sonos hat ueberlegene Audioqualitaet gegenueber 3.5mm Mini-Speaker
- `announce: true` duckt laufende Musik, spielt Antwort, Musik laeuft weiter
- Kein Kabelgewirr — alles WiFi
- AEC des XVF3800 funktioniert weiterhin (Reference-Signal via I2S Loopback)

### Datenfluss: Voice-Anfrage

```
ReSpeaker XVF3800 (Raum: Kueche)
    ↓ (Audio 16kHz, 16-bit PCM via WiFi / ESPHome Native API)
HA Assist Pipeline (PC1)
    ├─ Wake Word: micro_wake_word (lokal auf ESP32-S3)
    ├─ STT: Whisper (Wyoming)
    └─ Intent: MindHome Conversation Agent
        ↓
conversation.py → POST /api/assistant/chat
    Payload: {
      "text": "Transkribierter Text",
      "person": null,
      "room": "Kueche",
      "device_id": "esphome_respeaker_kueche",
      "voice_metadata": {duration, volume, wpm, word_count, source}
    }
        ↓
PC2: Brain.process()
    ├─ speaker_recognition.identify(device_id, room, audio_metadata)
    ├─ Person → Context fuer LLM
    ├─ Ollama → Antwort generiert
    └─ Response zurueck an PC1
        ↓
HA: Piper TTS → Audio-URL generiert
        ↓
ESPHome on_tts_end Trigger
    └─ homeassistant.service: media_player.play_media
       ├─ entity_id: media_player.sonos_kueche
       ├─ media_content_id: <TTS Audio URL>
       ├─ media_content_type: music
       └─ announce: true  ← duckt Musik, spielt Antwort, Musik weiter
```

---

## 2. Erkennungsmethoden (Prioritaetsreihenfolge)

Die `identify()`-Methode in `speaker_recognition.py` durchlaeuft eine Fallback-Kette:

### Methode 1: Device-Mapping (Confidence: 0.95)

**Datei:** `assistant/assistant/speaker_recognition.py`, Zeilen 179-199

Ordnet Hardware-Device-IDs direkt Personen zu. Zuverlaessigste Methode.

```yaml
# settings.yaml
speaker_recognition:
  device_mapping:
    esphome_respeaker_kueche: "max"
    esphome_respeaker_schlafzimmer: "lisa"
```

**Staerken:**
- Hoechste Confidence (0.95)
- Kein ML noetig, deterministisch
- Sofort einsatzbereit

**Schwaechen:**
- Statisch — wenn jemand anderes am gleichen Speaker spricht, wird falsch erkannt
- Braucht manuelle Konfiguration pro Device

**Status:** `device_mapping: {}` — **nicht konfiguriert**

---

### Methode 2: Room + Presence (Confidence: 0.80)

**Datei:** `speaker_recognition.py`, Zeilen 202-211, 264-293

Kombiniert HA `person.*` Entities (wer ist zuhause) mit Raum-Zuordnung.

```python
# Logik:
# 1. Alle Personen die "home" sind ermitteln
# 2. Falls Motion-Sensor im Raum → wer hat sich bewegt?
# 3. Falls preferred_room in person_profiles passt → diese Person
```

**Staerken:**
- Nutzt vorhandene HA-Infrastruktur
- Gut fuer Raeume mit nur einem Nutzer

**Schwaechen:**
- Braucht Motion-Sensoren fuer praezise Raum-Zuordnung
- Mehrere Personen im selben Raum → Fallback noetig

---

### Methode 3: Sole Person Home (Confidence: 0.85)

**Datei:** `speaker_recognition.py`, Zeilen 214-223

Wenn nur eine Person zuhause ist, muss sie der Sprecher sein.

```python
persons_home = [p for p in ha_states if p.state == "home"]
if len(persons_home) == 1:
    return persons_home[0]  # Confidence: 0.85
```

**Staerken:**
- Logisch zwingend bei Single-Person
- Kein zusaetzlicher Sensor noetig

**Schwaechen:**
- Funktioniert nur bei <= 1 Person zuhause
- Gaeste werden nicht erkannt

---

### Methode 4: Voice Feature Matching (Confidence: 0.30 - 0.90)

**Datei:** `speaker_recognition.py`, Zeilen 225-240, 312-381

Vergleicht Audio-Merkmale mit gespeicherten Profilen.

**Genutzte Features (nur 3):**

| Feature | Beschreibung | Schwaeche |
|---------|-------------|-----------|
| WPM | Words Per Minute | Variiert stark nach Kontext |
| Duration | Sprechdauer | Abhaengig von Satzlaenge |
| Volume | RMS-Lautstaerke | Abhaengig von Entfernung |

**Scoring-Algorithmus:**
```
fuer jedes Profil:
  wpm_diff = |sprecher_wpm - profil_wpm| / max(profil_wpm, 1)
  duration_diff = |dauer - profil_dauer| / max(profil_dauer, 1)
  volume_diff = |vol - profil_volume| / max(profil_volume, 0.01)

  avg_score = durchschnitt(features)
  sample_bonus = min(0.1, sample_count * 0.01)    # max +0.1
  recency_bonus = exponentiell (letzte 10 Min bevorzugt)

  final_score = avg_score * 0.7 + sample_bonus + recency_bonus
```

**Minimum Samples:** 3 (bevor Matching startet)

**SICHERHEITSWARNUNG (F-048):**
> Voice-Features (WPM, Dauer, Lautstaerke) sind KEIN sicheres Identifikationsmerkmal —
> sie koennen leicht gefaelscht werden. Ergebnis wird mit `spoofable: True` markiert.
> NICHT fuer sicherheitsrelevante Aktionen verwenden!

---

### Methode 5: Last-Speaker Cache (Confidence: 0.20 - 0.50)

**Datei:** `speaker_recognition.py`, Zeilen 242-255

Speichert zuletzt erkannte Person in RAM mit Time-Decay.

```python
age_minutes = (now - last_identified) / 60
cache_confidence = max(0.2, 0.5 - age_minutes / 120)
# Nach 2h sinkt Confidence auf 0.2
```

**Schwaechen:**
- Nur in Memory, weg nach Neustart
- Confidence sinkt schnell
- Keine Persistierung

---

### Methode 6: Voice Embeddings (Phase 9.6) — UNVOLLSTAENDIG

**Datei:** `speaker_recognition.py`, Zeilen 490-580

**Was implementiert IST:**
- Cosinus-Aehnlichkeit zwischen Embeddings (`identify_by_embedding()`)
- EMA-Verschmelzung fuer kontinuierliches Lernen (`store_embedding()`, alpha=0.3)
- Redis-Storage (`mha:speaker:embedding:{person_id}`)

**Was NICHT implementiert IST:**
- Embedding-Extraktion aus Audio (kein ML-Modell geladen)
- `identify_by_embedding()` wird **nirgends aufgerufen**
- `store_embedding()` wird **nirgends aufgerufen**
- Keine Integration in die Erkennungs-Kette
- Kein `embedding_model` Parameter in settings.yaml

**Fazit:** Zu ~40% implementiert — nur Storage/Query-Seite, keine Generierung.

---

## 3. Konfiguration (settings.yaml)

```yaml
speaker_recognition:
  enabled: false          # DEAKTIVIERT!
  min_confidence: 0.7
  fallback_ask: true      # Nicht implementiert in brain.py
  max_profiles: 10
  device_mapping: {}      # Leer
```

---

## 4. Bekannte Luecken

| # | Luecke | Schwere | Beschreibung |
|---|--------|---------|-------------|
| L1 | Voice Embeddings toter Code | Hoch | `identify_by_embedding()` existiert, wird nie aufgerufen |
| L2 | Speaker Recognition deaktiviert | Hoch | `enabled: false`, `device_mapping: {}` |
| L3 | Voice-Features zu simpel | Mittel | Nur 3 Features, leicht spoofbar |
| L4 | `fallback_ask` nicht implementiert | Mittel | Config-Flag existiert, brain.py fragt nie "Wer spricht?" |
| L5 | `device_id` fehlt im Addon Voice-Endpoint | Mittel | `/api/chat/voice` liest `device_id` nicht aus Request |
| L6 | Kein Profil-Backup auf Disk | Mittel | Redis-only, verloren nach Crash |
| L7 | Kein Audit-Logging | Niedrig | `set_current_speaker()` loggt nicht in History |
| L8 | Cache nicht persistent | Niedrig | `_last_speaker` nur in RAM |

---

## 5. Hardware

### 5.1 Mikrofon: ReSpeaker XMOS XVF3800 mit Gehaeuse + XIAO ESP32-S3

**Produkt:** [Seeed Studio ReSpeaker XVF3800 With Case + XIAO ESP32S3 (p-6628)](https://www.seeedstudio.com/ReSpeaker-XVF3800-With-Case-XIAO-ESP32S3-p-6628.html)

**Preis:** $64.90 / ~55 EUR

**Warum dieses Modell:**
- Komplett vormontiert mit Gehaeuse — kein Loeten, sofort einsatzbereit
- XIAO ESP32-S3 bereits aufgeloetet → WiFi + BLE 5.0 out-of-the-box
- USB-C fuer Stromversorgung (kein separates Netzteil noetig, USB-Adapter reicht)
- Plug-and-Play ESPHome & Home Assistant Kompatibilitaet
- 3.5mm Klinke vorhanden, wird aber NICHT genutzt → Ausgabe via Sonos

### Spezifikationen

| Eigenschaft | Wert |
|------------|------|
| **Produkt** | ReSpeaker XVF3800 With Case + XIAO ESP32S3 (p-6628) |
| **Preis** | $64.90 / ~55 EUR |
| Mikrofone | 4x bottom-firing MEMS, kreisfoermig |
| Voice Processor | XMOS XVF3800 (xcore.ai) |
| Companion MCU | Seeed XIAO ESP32-S3 (mit PSRAM) |
| Audio-Interface | I2S (16kHz / 48kHz, 32-bit) |
| Speaker-Ausgang | 3.5mm Klinke (nicht genutzt → Sonos) |
| LED-Ring | 12 addressierbare LEDs |
| Reichweite | 360 Grad, bis 5 Meter |
| Konnektivitaet | WiFi 802.11 b/g/n, Bluetooth 5.0, USB-C |
| Gehaeuse | Ja, vormontiert |
| Steuerung | I2C (ESP32-S3 → XVF3800) |

### 5.2 Audio-Ausgabe: Sonos Speaker

**Warum Sonos statt 3.5mm Mini-Speaker:**
- Ueberlegene Audioqualitaet fuer TTS-Antworten
- `announce: true` Feature: duckt laufende Musik → spielt TTS → Musik laeuft weiter
- Bereits in jedem Raum vorhanden (oder geplant)
- Kein Kabelgewirr — alles ueber LAN/WiFi
- Sonos HA-Integration ist stabil und gut dokumentiert

**Sonos TTS-Voraussetzungen:**
- TCP Port 1443 muss vom HA-Host zu jedem Sonos-Geraet erreichbar sein
- Sonos muss als `media_player.*` Entity in HA eingerichtet sein
- Piper TTS muss Audio-URLs generieren (Standard bei HA Assist Pipeline)

**Raum-zu-Sonos Mapping (Beispiel):**

| Raum | Voice Satellite | Device-Type | Sonos Entity |
|------|----------------|-------------|--------------|
| Kueche | `esphome_respeaker_kueche` | ReSpeaker XVF3800 | `media_player.sonos_kueche` |
| Wohnzimmer | `esphome_respeaker_wohnzimmer` | ReSpeaker XVF3800 | `media_player.sonos_wohnzimmer` |
| Schlafzimmer | `esphome_respeaker_schlafzimmer` | ReSpeaker XVF3800 | `media_player.sonos_schlafzimmer` |
| Buero | `esphome_respeaker_buero` | ReSpeaker XVF3800 | `media_player.sonos_buero` |
| Flur | `esphome_atom_echo_flur` | Atom Echo | `media_player.sonos_flur` |
| Bad | `esphome_atom_echo_bad` | Atom Echo | `media_player.sonos_bad` |

### 5.3 Zweit-Satellite: M5Stack Atom Echo

**Produkt:** [M5Stack ATOM Echo Smart Speaker Dev Kit](https://shop.m5stack.com/products/atom-echo-smart-speaker-dev-kit)

**Preis:** ~$13 / ~12 EUR

**Einsatzzweck:** Kompakter Voice-Satellite fuer Nebenraeume (Flur, Bad, Gaestezimmer)
wo kein Premium-Mikrofon noetig ist.

| Eigenschaft | Wert |
|------------|------|
| SoC | ESP32-PICO-D4 (240MHz, Dual Core) |
| Mikrofon | SPM1423 PDM (1x, mono) |
| Speaker | NS4168 I2S (0.5W) — wird NICHT genutzt → Sonos |
| Groesse | 24 x 24 x 17 mm (winzig!) |
| Flash | 4 MB |
| LED | 1x SK6812 RGB |
| Konnektivitaet | WiFi 802.11 b/g/n, Bluetooth 4.2 |
| Stromversorgung | USB-C |
| I2S Mic Pin | GPIO23 (PDM) |
| I2S Speaker Pin | GPIO22 (nicht genutzt) |
| I2S BCLK | GPIO19 |
| I2S LRCLK | GPIO33 |

**Vergleich ReSpeaker vs. Atom Echo:**

| Eigenschaft | ReSpeaker XVF3800 | M5Stack Atom Echo |
|------------|-------------------|-------------------|
| Preis | ~55 EUR | ~12 EUR |
| Mikrofone | 4x MEMS (kreisfoermig) | 1x PDM |
| Audio DSP | XMOS XVF3800 (AEC, Beamforming, DoA) | Keiner (Software-only) |
| Reichweite | 5m, 360 Grad | ~2-3m, omnidirektional |
| Geraeuschunterdrueckung | Hardware (on-chip) | Software (ESPHome) |
| DoA | Ja (Azimut-Winkel) | Nein |
| Speaker Recognition | Exzellent (sauberes Signal) | Grundlegend (verrauschter) |
| Wake Word | ESP32-S3 (leistungsfaehiger) | ESP32 (knapper Speicher) |
| Empfohlen fuer | Hauptraeume (Kueche, Wohnzimmer) | Nebenraeume (Flur, Bad) |

### On-Chip Audio-Processing (XVF3800)

Alle Verarbeitung passiert **auf dem Chip**, bevor Audio den ESP32-S3 erreicht:

| Stufe | Beschreibung | Vorteil fuer Erkennung |
|-------|-------------|----------------------|
| **AEC** | Acoustic Echo Cancellation, Full-Duplex | Kein Echo von TTS im Signal |
| **Beamforming** | 3 gleichzeitige Beams (1 scannend + 2 fokussiert) | Richtet sich auf Sprecher aus |
| **DoA** | Direction of Arrival — Azimut-Winkel pro Beam | Raeumliche Sprecher-Unterscheidung |
| **Dereverberation** | Reduziert Raumhall | Konsistentere Voice-Features |
| **Noise Suppression** | Dynamische Rauschunterdrueckung | Sauberes Signal |
| **VAD** | Voice Activity Detection | Erkennt ob jemand spricht |
| **AGC** | Auto Gain Control (60dB Bereich) | Konsistente Lautstaerke |

### Direction of Arrival (DoA) — Game Changer

Der XVF3800 liefert **Azimut-Winkel** fuer erkannte Sprecher:

- `AEC_AZIMUTH_VALUES`: Roher Azimut pro Beam (Grad/Radiant)
- `AUDIO_MGR_SELECTED_AZIMUTHS`: Kombinierte Sprecher-Richtung (NaN wenn niemand spricht)
- **2 Sprecher gleichzeitig** trackbar via fokussierte Beams

**Anwendung fuer Speaker Recognition:**
```
Raum-Layout:
  Schreibtisch (Max)  → Azimut ~45°
  Sofa (Lisa)         → Azimut ~200°
  Esstisch (Gast)     → Azimut ~310°

→ DoA + Room = Sprecher-Identifikation ohne Voice Embeddings
→ DoA + Embeddings = noch hoehere Confidence
```

### I2S Pin-Belegung (XIAO ESP32-S3)

| Signal | GPIO | Richtung |
|--------|------|----------|
| I2S BCK (Bit Clock) | GPIO8 | ESP32 → XVF3800 |
| I2S WS (Word Select / LRCLK) | GPIO7 | ESP32 → XVF3800 |
| I2S DATA_OUT (Speaker) | GPIO44 | ESP32 → DAC |
| I2S DATA_IN (Mic) | GPIO43 | XVF3800 → ESP32 |

---

## 6. ESPHome Integration

### ESPHome YAML-Vorlage (ReSpeaker XVF3800 + Sonos)

> **WICHTIG:** Kein `speaker:` Block noetig — TTS-Ausgabe laeuft ueber Sonos.
> Der ReSpeaker ist reines Mikrofon + Wake Word Geraet.

```yaml
# ============================================================
# ReSpeaker XVF3800 + XIAO ESP32-S3 — Voice Satellite
# Mic-Input: ReSpeaker XVF3800 (4-Mic Array, on-chip DSP)
# TTS-Output: Sonos Speaker via HA media_player.play_media
# ============================================================

esphome:
  name: respeaker-kueche
  friendly_name: "ReSpeaker Kueche"

esp32:
  board: esp32-s3-devkitc-1
  framework:
    type: esp-idf

# --- WiFi ---
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

# --- Externe Komponente fuer XVF3800 Board-Support ---
external_components:
  - source: github://formatbce/esphome_xvf3800
    components: [xvf3800]

# --- I2S Audio (nur Input, kein Speaker) ---
i2s_audio:
  - id: i2s_in
    i2s_lrclk_pin: GPIO7
    i2s_bclk_pin: GPIO8

microphone:
  - platform: i2s_audio
    id: xvf3800_mic
    adc_type: external
    i2s_audio_id: i2s_in
    i2s_din_pin: GPIO43
    pdm: false
    bits_per_sample: 16bit
    sample_rate: 16000

# --- KEIN speaker: Block! TTS geht ueber Sonos ---

# --- Wake Word (lokal auf ESP32-S3) ---
micro_wake_word:
  models:
    - model: hey_jarvis
  on_wake_word_detected:
    - voice_assistant.start:

# --- Voice Assistant (ohne Speaker, mit Sonos TTS-Redirect) ---
voice_assistant:
  microphone: xvf3800_mic
  # KEIN speaker: Parameter → kein lokaler Audio-Output
  use_wake_word: true
  noise_suppression_level: 2
  auto_gain: 31dBFS

  # === SONOS TTS-AUSGABE ===
  # on_tts_end liefert die TTS Audio-URL als Variable "x"
  # Diese URL wird an den Sonos Speaker im selben Raum gesendet
  on_tts_end:
    - homeassistant.service:
        service: media_player.play_media
        data:
          entity_id: media_player.sonos_kueche    # ← ANPASSEN pro Raum!
          media_content_id: !lambda 'return x;'
          media_content_type: music
          announce: "true"                         # Duckt Musik, spielt TTS, Musik weiter

  # Optional: LED-Feedback waehrend Verarbeitung
  on_listening:
    - light.turn_on:
        id: led_ring
        effect: "Listening"
  on_stt_end:
    - light.turn_on:
        id: led_ring
        effect: "Processing"
  on_end:
    - light.turn_off:
        id: led_ring

# --- LED Ring (12 LEDs, optional fuer visuelles Feedback) ---
light:
  - platform: esp32_rmt_led_strip
    id: led_ring
    pin: GPIO1
    num_leds: 12
    rmt_channel: 0
    chipset: WS2812
    rgb_order: GRB
    effects:
      - addressable_rainbow:
          name: "Listening"
          speed: 30
      - addressable_color_wipe:
          name: "Processing"
          colors:
            - red: 0
              green: 0
              blue: 100%
          add_led_interval: 50ms

# --- API & OTA ---
api:
  encryption:
    key: !secret api_encryption_key

ota:
  - platform: esphome
    password: !secret ota_password
```

### ESPHome YAML-Vorlage (M5Stack Atom Echo + Sonos)

> **WICHTIG:** Auch beim Atom Echo wird der eingebaute 0.5W Speaker NICHT genutzt.
> TTS laeuft ueber Sonos. Das spart RAM und verbessert die Audioqualitaet erheblich.

```yaml
# ============================================================
# M5Stack Atom Echo — Voice Satellite (Nebenraeume)
# Mic-Input: SPM1423 PDM Mikrofon (1x, mono)
# TTS-Output: Sonos Speaker via HA media_player.play_media
# ============================================================

esphome:
  name: atom-echo-flur
  friendly_name: "Atom Echo Flur"
  min_version: 2025.5.0

esp32:
  board: m5stack-atom
  framework:
    type: esp-idf

# --- WiFi ---
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

# --- I2S Audio (nur Mikrofon, kein Speaker) ---
i2s_audio:
  - id: i2s_audio_bus
    i2s_lrclk_pin: GPIO33
    i2s_bclk_pin: GPIO19

microphone:
  - platform: i2s_audio
    id: atom_mic
    adc_type: external
    i2s_audio_id: i2s_audio_bus
    i2s_din_pin: GPIO23
    pdm: true

# --- KEIN speaker: Block! TTS geht ueber Sonos ---

# --- Wake Word (lokal auf ESP32) ---
micro_wake_word:
  models:
    - model: hey_jarvis
  on_wake_word_detected:
    - voice_assistant.start:

# --- Voice Assistant (ohne Speaker, mit Sonos TTS-Redirect) ---
voice_assistant:
  microphone: atom_mic
  use_wake_word: true
  noise_suppression_level: 2
  auto_gain: 31dBFS

  on_tts_end:
    - homeassistant.service:
        service: media_player.play_media
        data:
          entity_id: media_player.sonos_flur       # ← ANPASSEN pro Raum!
          media_content_id: !lambda 'return x;'
          media_content_type: music
          announce: "true"

  # LED-Feedback (1x RGB LED)
  on_listening:
    - light.turn_on:
        id: led
        blue: 100%
        red: 0%
        green: 0%
        brightness: 75%
  on_stt_end:
    - light.turn_on:
        id: led
        blue: 0%
        red: 0%
        green: 100%
        brightness: 50%
  on_end:
    - light.turn_off:
        id: led

# --- RGB LED ---
light:
  - platform: esp32_rmt_led_strip
    id: led
    pin: GPIO27
    num_leds: 1
    rmt_channel: 0
    chipset: SK6812
    rgb_order: GRB

# --- API & OTA ---
api:
  encryption:
    key: !secret api_encryption_key

ota:
  - platform: esphome
    password: !secret ota_password
```

> **Hinweis zum Atom Echo Wake Word:** Der ESP32-PICO-D4 hat weniger RAM als
> der ESP32-S3. `micro_wake_word` funktioniert, aber nur mit kleineren Modellen.
> Falls Speicherprobleme auftreten, Wake Word in HA statt lokal ausfuehren lassen.

### Pro-Raum Anpassung

Fuer jeden Raum muss nur der `name`, `friendly_name` und die `entity_id` des Sonos angepasst werden:

```yaml
# ReSpeaker (Hauptraeume):
#   respeaker-kueche      → media_player.sonos_kueche
#   respeaker-wohnzimmer   → media_player.sonos_wohnzimmer
#   respeaker-schlafzimmer → media_player.sonos_schlafzimmer
#   respeaker-buero        → media_player.sonos_buero
#
# Atom Echo (Nebenraeume):
#   atom-echo-flur         → media_player.sonos_flur
#   atom-echo-bad          → media_player.sonos_bad
#   atom-echo-gaestezimmer → media_player.sonos_gaestezimmer
```

> **Tipp:** Alternativ kann das Raum-zu-Sonos Mapping auch als HA-Automation
> geloest werden (ein Blueprint fuer alle Raeume). Dann braucht die ESPHome-Config
> kein hartcodiertes `entity_id` und der `on_tts_end` Block feuert ein HA-Event,
> das die Automation abfaengt und den richtigen Sonos waehlt.

### Bekannter Bug: TTS-Loop (ESPHome 2025.5+)

> **ACHTUNG:** Ab ESPHome 2025.5 gibt es einen bekannten Bug, bei dem
> `on_tts_end` mit `media_player.play_media` in einer Endlosschleife laufen kann.
> **Workaround:** In `on_tts_end` eine kurze Verzoegerung (`delay: 500ms`) einbauen
> oder auf `on_tts_stream_end` wechseln, sobald dieses Event auch fuer externe
> Media Player verfuegbar ist (Feature Request: esphome/feature-requests#3148).

### Integrations-Wege

#### Weg A: Standard + Sonos (empfohlen fuer Start)

```
ReSpeaker XVF3800 (Mic)
    ↓ ESPHome Native API / WiFi
HA Assist Pipeline
    ├── Wake Word (lokal auf ESP32-S3)
    ├── STT: Whisper (Wyoming)
    ├── Intent: MindHome Conversation Agent
    ├── TTS: Piper → generiert Audio-URL
    └── on_tts_end → media_player.play_media(Sonos, announce=true)
                            ↓
                    Sonos Speaker (Ausgabe)
```

- Sofort funktionsfaehig mit der YAML-Vorlage oben
- Wake Word lokal auf ESP32-S3
- `device_id` verfuegbar fuer Device-Mapping (95% Confidence)
- Raum-Erkennung ueber HA Device Areas automatisch
- Sonos duckt Musik → spielt Antwort → Musik weiter

#### Weg B: Wyoming STT Wrapper (fuer Voice Embeddings)

```
ReSpeaker XVF3800 (Mic)
    ↓ ESPHome Native API / WiFi
HA Assist Pipeline
    ↓
Custom Wyoming STT Wrapper (auf PC2)
    ├── Faengt Audio ab (16kHz PCM)
    ├── Extrahiert Speaker Embedding (ECAPA-TDNN)
    ├── Leitet Audio an Whisper weiter fuer STT
    └── Sendet Embedding an MindHome Speaker Recognition
    ↓
TTS: Piper → on_tts_end → Sonos
```

- Ermoeglicht Voice Embeddings aus sauberem XVF3800-Audio
- Kein zusaetzlicher Audio-Stream noetig
- Architektonisch sauber (Wyoming ist Standard)
- Sonos-Ausgabe funktioniert identisch wie bei Weg A

#### Weg C: UDP Audio Streaming (parallel)

```
ReSpeaker XVF3800 (Mic)
    ↓ ESP32-S3
    ├── Voice Assistant (normal) → HA → Sonos
    └── UDP Stream (parallel) → PC2 Backend (Embeddings)
```

- Seeed-dokumentiert: ESP32-S3 kann Audio parallel per UDP streamen
- Backend extrahiert Embeddings aus UDP-Stream
- Unabhaengig von HA Pipeline
- Sonos-Ausgabe laeuft weiterhin ueber HA

---

## 7. Implementierungsstrategie — Meine Empfehlung

> **Ziel:** Speaker Recognition zuverlaessig zum Laufen bringen,
> perfekte Sonos-Integration, beide Satellite-Typen unterstuetzt.

### Uebersicht: Was muss passieren

```
JETZT (Software-Fixes, ohne Hardware):
  ├── A. settings.yaml: device_mapping Struktur anlegen
  ├── B. speaker_recognition.py: device_mapping aus Config laden
  ├── C. chat.py (Addon): device_id durchschleifen
  ├── D. settings.yaml: enabled: true
  └── E. Tests + Validierung

WENN HARDWARE DA (ReSpeaker + Atom Echo):
  ├── F. ESPHome flashen (beide YAML-Vorlagen)
  ├── G. HA: Satellites + Sonos + Areas einrichten
  ├── H. Device-IDs in settings.yaml eintragen
  └── I. End-to-End Test

SPAETER (Optimierung):
  ├── J. DoA-Integration (nur ReSpeaker)
  ├── K. Voice Embeddings fertigstellen
  └── L. Fallback-Dialog + Robustheit
```

---

### Phase 1: Software-Fixes (JETZT, ohne Hardware)

> **Empfehlung:** Diese Aenderungen JETZT machen, damit beim Eintreffen
> der Hardware sofort alles funktioniert. Alles reine Code-Arbeit.

#### 1.1 — `settings.yaml`: Device-Mapping + Aktivierung

```yaml
# VORHER:
speaker_recognition:
  enabled: false
  min_confidence: 0.7
  fallback_ask: true
  max_profiles: 10
  device_mapping: {}

# NACHHER:
speaker_recognition:
  enabled: true                     # ← AKTIVIEREN
  min_confidence: 0.6               # ← Etwas niedriger fuer Anfang
  fallback_ask: true
  max_profiles: 10
  device_mapping:                   # ← Wird befuellt wenn Hardware da
    # ReSpeaker Hauptraeume:
    # esphome_respeaker_kueche: "max"
    # esphome_respeaker_wohnzimmer: "lisa"
    # Atom Echo Nebenraeume:
    # esphome_atom_echo_flur: "max"
    # esphome_atom_echo_bad: "lisa"
```

**Datei:** `assistant/config/settings.yaml`

#### 1.2 — `chat.py`: device_id im Addon Voice-Endpoint durchschleifen

**Problem:** `/api/chat/voice` extrahiert echte Audio-Metadaten (gut!),
aber leitet `device_id` NICHT weiter → Device-Mapping kann nie greifen.

**Fix:**

```python
# In addon/rootfs/opt/mindhome/routes/chat.py
# Beim Parsen der Form-Daten (ca. Zeile 470):
device_id = form.get("device_id", None)   # ← NEU

# Beim Erstellen des chat_payload (ca. Zeile 660):
chat_payload = {
    "text": transcribed_text,
    "person": person,
    "room": room,
    "device_id": device_id,              # ← NEU
}
if voice_metadata:
    chat_payload["voice_metadata"] = voice_metadata
```

**Datei:** `addon/rootfs/opt/mindhome/routes/chat.py`

#### 1.3 — `speaker_recognition.py`: Sicherstellen device_mapping aus Config geladen wird

**Aktueller Stand:** `device_mapping` wird in `__init__` aus Config gelesen (Zeile 119).
Das funktioniert bereits, ABER: `device_mapping` steht aktuell als `{}` in settings.yaml
und ist dort auch nicht als Beispiel dokumentiert.

**Pruefen:** Dass `settings.yaml` tatsaechlich die `device_mapping` Struktur unterstuetzt
und dass die Keys die HA-Device-IDs sind (Format: `esphome_<name>`).

#### 1.4 — `conversation.py` (HA Integration): Bereits korrekt

**Gute Nachricht:** Die HA-Integration schleift `device_id` bereits korrekt durch:
```python
# ha_integration/.../conversation.py, Zeile 98:
if ha_device_id:
    payload["device_id"] = ha_device_id
```
→ Kein Fix noetig. Funktioniert out-of-the-box mit ESPHome Voice Satellites.

#### 1.5 — Pipeline-Verifizierung

Nach den Fixes muss folgende Kette stimmen:

```
ESPHome Voice Satellite
    ↓ (device_id wird von HA automatisch aus Device Registry gelesen)
HA Assist Pipeline
    ↓ ConversationInput.device_id
conversation.py → _detect_room(device_id) + payload["device_id"]
    ↓ POST /api/assistant/chat
main.py ChatRequest → device_id
    ↓
brain.py process(device_id=...)
    ↓
speaker_recognition.identify(device_id=...)
    → Methode 1: device_mapping Lookup → Person gefunden (0.95 Confidence)
    → Methode 2: Room + Presence (falls Mapping nicht matched)
    → Methode 3: Sole Person Home (falls nur einer da)
```

---

### Phase 2: Hardware-Setup (wenn ReSpeaker + Atom Echo da sind)

#### 2.1 — ESPHome Firmware flashen

| Geraet | YAML-Vorlage | Flash-Methode |
|--------|-------------|---------------|
| ReSpeaker XVF3800 | Sektion 6, "YAML-Vorlage ReSpeaker" | USB-C → ESPHome Web Flasher |
| M5Stack Atom Echo | Sektion 6, "YAML-Vorlage Atom Echo" | USB-C → ESPHome Web Flasher |

**Pro Geraet anpassen:**
1. `name:` und `friendly_name:` (eindeutig pro Raum)
2. `entity_id:` in `on_tts_end` → auf den richtigen Sonos zeigen
3. `wifi:` Credentials via `!secret`

#### 2.2 — HA einrichten

| Schritt | Was | Wo |
|---------|-----|---|
| 2.2a | ESPHome Devices in HA adoptieren | Settings → Devices → ESPHome |
| 2.2b | Device Area zuweisen (Kueche, Flur, etc.) | Device → Edit → Area |
| 2.2c | Sonos pruefen: TCP Port 1443 erreichbar | `nc -zv <sonos-ip> 1443` |
| 2.2d | Assist Pipeline konfigurieren | Settings → Voice Assistants |
| 2.2e | STT: Whisper, TTS: Piper, Conversation: MindHome | Pipeline Settings |

#### 2.3 — Device-Mapping befuellen

Nachdem die Geraete in HA sind, die echten Device-IDs auslesen:

```bash
# In HA Developer Tools → States → nach "esphome" filtern
# Oder: Settings → Devices → ESPHome → Device-ID notieren
```

Dann in `settings.yaml`:

```yaml
speaker_recognition:
  enabled: true
  device_mapping:
    esphome_respeaker_kueche: "max"        # Wer sitzt meist in der Kueche?
    esphome_respeaker_wohnzimmer: "max"    # Oder: shared → leer lassen
    esphome_atom_echo_flur: ""             # Shared → kein Default-Mapping
    esphome_atom_echo_bad: ""              # Shared → Room+Presence greift
```

> **Strategie:** Nur Raeume mit klarem Hauptnutzer mappen.
> Shared-Raeume leer lassen → Methode 2/3 (Presence) uebernimmt.

#### 2.4 — End-to-End Tests

| # | Test | Erwartung |
|---|------|-----------|
| T1 | "Hey Jarvis, wie ist das Wetter?" (ReSpeaker Kueche) | STT → MindHome → Antwort auf Sonos Kueche |
| T2 | Gleicher Test waehrend Sonos Musik spielt | Musik duckt → Antwort → Musik weiter |
| T3 | "Hey Jarvis, wie heisse ich?" (gemapptes Device) | Antwort mit richtigem Namen (Speaker erkannt) |
| T4 | Gleicher Test vom Atom Echo (Flur) | Funktioniert, evtl. anderer Erkennungsweg |
| T5 | Test mit 2 Personen zuhause | Richtiger Name je nach Device/Raum |
| T6 | Test mit nur 1 Person zuhause | Sole-Person-Home greift (0.85 Confidence) |

---

### Phase 3: DoA-Integration — nur ReSpeaker (spaeter)

> **Wann:** Nachdem Phase 1+2 stabil laufen.
> **Nur fuer ReSpeaker** — der Atom Echo hat kein Mic-Array und kann kein DoA.

| Schritt | Beschreibung | Aufwand |
|---------|-------------|---------|
| 3.1 | ESPHome Custom Component: DoA via I2C aus XVF3800 lesen | 2-4h |
| 3.2 | DoA-Wert als `audio_direction` in Voice-Metadata mitschicken | 1h |
| 3.3 | `speaker_recognition.py`: DoA in Erkennungs-Kette einbauen | 2-3h |
| 3.4 | Raum-Kalibrierung: "Max sitzt bei ~45 Grad, Lisa bei ~200 Grad" | Config |

**Vorteil:** In Raeumen mit ReSpeaker koennen 2+ Personen unterschieden werden,
OHNE Voice Embeddings — rein ueber Richtung + Presence.

---

### Phase 4: Voice Embeddings fertigstellen (spaeter)

> **Wann:** Wenn Phase 1-3 stabil laufen und mehr Praezision gewuenscht ist.
> **Fuer beide Geraete** — braucht nur Audio-Stream, kein spezielles Mic.

| Schritt | Beschreibung | Aufwand |
|---------|-------------|---------|
| 4.1 | SpeechBrain ECAPA-TDNN (~40MB) auf PC2 deployen | 1-2h |
| 4.2 | Wyoming STT Wrapper: Audio abfangen, Embedding extrahieren, an Whisper weiterleiten | 4-6h |
| 4.3 | `identify_by_embedding()` in Erkennungs-Kette als Methode 2 (nach Device-Mapping) | 2h |
| 4.4 | `store_embedding()` bei jeder erfolgreichen Erkennung aufrufen (lernt staendig) | 1h |
| 4.5 | Enrollment: "Hey Jarvis, lerne meine Stimme" → 3 Saetze sprechen | 3-4h |

**Empfohlenes Embedding-Modell:**

| Modell | Groesse | Output | Deutsch | Eignung |
|--------|---------|--------|---------|---------|
| **SpeechBrain ECAPA-TDNN** | ~40MB | 192-d Vektor | Gut (multilingual) | Empfohlen |
| Resemblyzer | ~500MB | 256-d Vektor | Mittel | Alternative |
| Wav2Vec2 (Meta) | ~360MB | 768-d Vektor | Sehr gut | Gross, aber praezise |

---

### Phase 5: Fallback-Dialog + Robustheit (spaeter)

| Schritt | Beschreibung | Aufwand |
|---------|-------------|---------|
| 5.1 | Bei Confidence < 0.6: "Bist du Max oder Lisa?" per Sonos fragen | 2-3h |
| 5.2 | Naechste Antwort als Name-Confirmation erkennen | 2h |
| 5.3 | Profil-Backup: Redis → YAML Disk-Backup alle 5 Min | 1h |
| 5.4 | Audit-Logging: Jede Erkennung in `mha:speaker:history` | 1h |
| 5.5 | Dashboard-Widget: Wer wurde wann wo erkannt | 2-3h |

---

### Priorisierung — Was zuerst?

```
PRIORITAET 1 (MUSS — damit es ueberhaupt funktioniert):
  ✅ Phase 1.1: settings.yaml → enabled: true + device_mapping Struktur
  ✅ Phase 1.2: chat.py → device_id durchschleifen
  ✅ Phase 2.1-2.4: Hardware flashen + HA einrichten + Sonos testen

PRIORITAET 2 (SOLL — damit es zuverlaessig funktioniert):
  📋 Phase 3: DoA fuer ReSpeaker-Raeume (Multi-Person Unterscheidung)
  📋 Phase 5.1-5.2: Fallback-Dialog ("Wer bist du?")

PRIORITAET 3 (KANN — fuer Perfektion):
  📋 Phase 4: Voice Embeddings (echte Stimmenerkennung)
  📋 Phase 5.3-5.5: Backup, Logging, Dashboard
```

---

## 8. Sicherheitsempfehlungen

```python
# 1. Nie einer einzelnen Methode allein vertrauen fuer Sicherheitsaktionen
confidence_thresholds = {
    "device_mapping": 0.95,      # Sehr zuverlaessig
    "embedding": 0.92,           # Gut, aber nicht 100%
    "room_presence": 0.80,       # Kontext-abhaengig
    "voice_features": 0.70,      # Nur als Hint, spoofbar!
    "doa_angle": 0.75,           # Raeumlich, nicht identitaetsbasiert
}

# 2. Cross-Validation fuer sicherheitsrelevante Aktionen
if action in SECURITY_ACTIONS:
    require_multiple_methods(min_combined_confidence=0.95)

# 3. Voice-Features NIE allein fuer Authentifizierung
if method == "voice_features" and not secondary_method:
    mark_as("spoofable")
    deny_security_actions()
```

---

## 9. Relevante Dateien

| Datei | Beschreibung |
|-------|-------------|
| `assistant/assistant/speaker_recognition.py` | Hauptlogik: identify(), Methoden 1-6 |
| `assistant/assistant/brain.py` (Zeilen 590-625) | Ruft identify() auf, setzt Person-Context |
| `assistant/config/settings.yaml` (Zeilen 459-464) | Speaker Recognition Konfiguration |
| `addon/rootfs/opt/mindhome/routes/chat.py` (Zeilen 462-660) | Voice-Endpoint, Audio-Verarbeitung |
| `ha_integration/custom_components/mindhome_assistant/conversation.py` | HA Conversation Agent, leitet an PC2 |

---

## 10. Quellen & Referenzen

### Hardware & Firmware — ReSpeaker XVF3800
- [Seeed Studio: ReSpeaker XVF3800 mit Gehaeuse + XIAO ESP32-S3 (p-6628)](https://www.seeedstudio.com/ReSpeaker-XVF3800-With-Case-XIAO-ESP32S3-p-6628.html) — das gewaehlte Modell
- [Seeed Studio: ReSpeaker XVF3800 Wiki](https://wiki.seeedstudio.com/respeaker_xvf3800_introduction/)
- [Seeed Studio: XVF3800 Home Assistant Integration](https://wiki.seeedstudio.com/respeaker_xvf3800_xiao_home_assistant/)
- [Seeed Studio: XVF3800 UDP Audio Streaming](https://wiki.seeedstudio.com/respeaker_xvf3800_xiao_udp_audio_stream/)
- [XMOS XVF3800 Datasheet](https://www.xmos.com/xvf3800)
- [XMOS XVF3800 Audio Pipeline Dokumentation](https://www.xmos.com/documentation/XM-014888-PC/html/modules/fwk_xvf/doc/datasheet/03_audio_pipeline.html)

### Hardware & Firmware — M5Stack Atom Echo
- [M5Stack Atom Echo Produktseite](https://shop.m5stack.com/products/atom-echo-smart-speaker-dev-kit)
- [M5Stack Atom Echo Dokumentation](https://docs.m5stack.com/en/atom/atomecho)
- [ESPHome Offizielles YAML fuer Atom Echo](https://github.com/esphome/wake-word-voice-assistants/blob/main/m5stack-atom-echo/m5stack-atom-echo.yaml)
- [HA Community: $13 Voice Assistant Guide (Atom Echo)](https://community.home-assistant.io/t/how-to-adopt-a-device-into-esphome-the-addition-to-the-13-voice-assistant-guide-m5stack-atom-echo/597138)

### ESPHome & Home Assistant
- [ESPHome Voice Assistant Component](https://esphome.io/components/voice_assistant/) — `on_tts_end` Trigger Dokumentation
- [ESPHome Micro Wake Word Component](https://esphome.io/components/micro_wake_word/)
- [ESPHome Ready-Made Projects (Voice Assistants)](https://esphome.io/projects/)
- [FormatBCE ESPHome XVF3800 Integration](https://community.home-assistant.io/t/respeaker-xmos-xvf3800-esphome-integration/927241)
- [Home Assistant Wyoming Protocol](https://www.home-assistant.io/integrations/wyoming/)

### Sonos TTS-Integration
- [HA Sonos Integration](https://www.home-assistant.io/integrations/sonos/) — `announce: true` Dokumentation
- [ESPHome Voice Assistant Speech Output to HA Media Player](https://community.home-assistant.io/t/esphome-voice-assistant-speech-output-to-home-assistant-media-player/588337) — Urspruenglicher Guide
- [Route Full Voice Assistant Responses to Sonos](https://community.home-assistant.io/t/esphome-route-full-voice-assistant-responses-to-sonos/917388)
- [Redirect Voice PE Replies to Sonos](https://community.home-assistant.io/t/redirect-voice-pe-replies-to-sonos/926652)
- [Voice PE → Play Replies on External Media Player](https://community.home-assistant.io/t/voice-pe-play-replies-on-an-external-media-playerer/976011)
- [Feature Request: on_tts_stream_end fuer Media Player](https://github.com/esphome/feature-requests/issues/3148) — TTS-Loop Bug Workaround

### Speaker Recognition / ML
- [SpeechBrain ECAPA-TDNN Speaker Verification](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)
