# Jarvis Assistant - Feature Audit & Verbesserungsvorschlaege

**Datum:** 2026-03-06
**Scope:** Vollstaendige Analyse aller Features, Architektur und Verbesserungspotentiale

---

## 1. Bestandsaufnahme: Was Jarvis heute kann

### 1.1 Kern-AI & Konversation
| Modul | Datei | Beschreibung |
|-------|-------|-------------|
| Brain | `brain.py` (9.868 Z.) | Zentraler Orchestrator, integriert alle Komponenten |
| Personality | `personality.py` (3.240 Z.) | Humor-Level 1-5, Sarkasmus, Running Gags |
| Context Builder | `context_builder.py` (1.283 Z.) | Prompt-Assembly mit Injection-Schutz |
| Model Router | `model_router.py` | Fast/Smart/Deep Routing nach Komplexitaet |
| Ollama Client | `ollama_client.py` | Lokale LLM-Inferenz |
| Dialogue State | `dialogue_state.py` | Konversationskontext & Intent-Tracking |
| Pre-Classifier | `pre_classifier.py` | Request-Kategorisierung fuer effizientes Routing |

### 1.2 Memory-Systeme
| Modul | Beschreibung |
|-------|-------------|
| Memory Manager | 3-Tier: Working (Redis), Episodic (ChromaDB), Semantic (Fakten) |
| Semantic Memory | Wissensbasis mit Embeddings (1.042 Z.) |
| Memory Extractor | Zieht Schluesselinformationen aus Gespraechen |
| Correction Memory | Lernt aus Nutzer-Korrekturen |
| Knowledge Base | Allgemeines Wissen (701 Z.) |
| Daily Summarizer | Erstellt Tageszusammenfassungen |

### 1.3 Proaktives System
| Modul | Beschreibung |
|-------|-------------|
| Proactive Manager | Event-Trigger, Urgency-Levels, Adaptive Cooldowns (4.904 Z.) |
| Health Monitor | CO2, Feuchte, Temperatur, Hydration-Reminders |
| Insight Engine | Cross-Referenz: Wetter+Fenster, Frost+Heizung, Kalender+Reise (1.665 Z.) |
| Activity Engine | Silence Matrix: Schlaf/Telefon/Film/Fokus/Gaeste erkennen (728 Z.) |
| Device Health | Anomalie-Erkennung: 30-Tage Rolling Average, 2-Sigma (608 Z.) |
| Threat Assessment | Sicherheitsanalyse fuer kritische Alerts |

### 1.4 Automation & Lernen
| Modul | Beschreibung |
|-------|-------------|
| Automation Engine | Pattern Detection, Presence Modes, Holiday Awareness (116.969 Z.) |
| Pattern Engine | State Tracking, Scene Detection, Motion Debouncing (104.814 Z.) |
| Learning Observer | 3+ Wiederholungen = Vorschlag, Zeit/Sequenz/Kontext-Patterns (728 Z.) |
| Anticipation Engine | Vorhersage mit 60-95% Confidence Thresholds (762 Z.) |
| Self Automation | NL → HA Automation, Whitelist, Rate Limiting (1.056 Z.) |
| Self Optimization | Auto-Tuning innerhalb sicherer Grenzen (774 Z.) |

### 1.5 Routinen & Zeitsteuerung
| Modul | Beschreibung |
|-------|-------------|
| Routine Engine | Morning Briefing, Gute Nacht, Gaeste-Modus, Urlaubs-Simulation (1.693 Z.) |
| Timer Manager | Software-Timer fuer Erinnerungen (911 Z.) |
| Calendar Intelligence | Gewohnheiten, Konflikte, Pendelzeit-Erkennung |
| Time Awareness | Tagesphase, Feiertage, Jahreszeiten, Sonnenauf-/untergang (613 Z.) |
| Seasonal Insight | Saisonale Anpassungen |

### 1.6 Spezial-Assistenten
| Modul | Beschreibung |
|-------|-------------|
| Cooking Assistant | Schritt-fuer-Schritt Rezepte, Timer, Allergien (969 Z.) |
| Music DJ | Mood+Aktivitaet+Tageszeit → Spotify-Genre, Feedback-Learning (969 Z.) |
| Wellness Advisor | Gesundheit, Fitness, Schlaf-Tracking (750 Z.) |
| Workshop Generator | Lern-Inhalte generieren |
| Workshop Library | Inhalte speichern/abrufen |

### 1.7 Personen & Praesenz
| Modul | Beschreibung |
|-------|-------------|
| Speaker Recognition | Multi-Methode: Device-Map, DoA, Voice Embeddings ECAPA-TDNN (963 Z.) |
| Visitor Manager | Klingel→Kamera→ID, "Lass rein" Workflow (750 Z.) |
| Mood Detector | Text-Ton, Stimm-Features, Geraete-Aktivitaet (949 Z.) |
| Follow-Me | Licht/Musik/Klima folgt Person von Raum zu Raum |

### 1.8 Energie & Klima
| Modul | Beschreibung |
|-------|-------------|
| Energy Optimizer | Strompreis-Alerts, Solar-Optimierung, Anomalie-Erkennung |
| Climate Model | Heiz-/Kuehl-Intelligenz |
| Light Engine | Circadiane Anpassung, Szenen (934 Z.) |
| Predictive Maintenance | Geraete-Lebenszyklus |
| Repair Planner | Wartungsplanung (1.689 Z.) |

### 1.9 Audio & Stimme
| Modul | Beschreibung |
|-------|-------------|
| Sound Manager | Auto-Volume, Sound Effects (650 Z.) |
| Ambient Audio | Hintergrundgeraeusch-Erkennung |
| TTS Enhancer | Emotion, Pausen, Sprechgeschwindigkeit |

### 1.10 API & Frontend
| Modul | Beschreibung |
|-------|-------------|
| FastAPI Server | `main.py` (7.809 Z.) - REST API + WebSocket |
| Flask Addon | `app.py` (41.666 Z.) - HA-seitige Anwendung |
| Dashboard UI | React SPA (`static/ui/app.js`, 633 KB) |
| Chat UI | `static/chat/index.html` (58 KB) |
| Workshop UI | `static/workshop/index.html` (320 KB) |
| WebSocket | Real-Time Streaming, emit_speaking, emit_proactive |

### 1.11 Sicherheit
- ~80+ Regex-Patterns fuer Prompt-Injection-Schutz
- SSRF-Schutz mit IP-Blocklists, DNS-Rebinding-Defense
- Command-Injection-Prevention (F-045)
- Service/Domain Whitelists, Config-Edit Whitelists
- Trust-Level System (Guest/Member/Owner)
- File-Upload Safety (50MB, Extension Whitelist, MIME Validation)

---

## 2. Neue Features (Priorisiert)

### 2.1 Proaktive Einkaufsliste (Prio: HOCH)

**Status Quo:** `inventory.py` trackt Bestaende mit Ablaufdatum und fuegt zu HA Shopping List hinzu.

**Verbesserungen:**

1. **Verbrauchsmuster-Erkennung:**
   - Inventory-Eintraege mit Verbrauchsrate tracken (z.B. Milch alle 3 Tage)
   - Proaktiv warnen: "Milch wird morgen alle sein, soll ich sie auf die Liste setzen?"
   - Lernend: je mehr Daten, desto genauer die Vorhersage

2. **Rezept-basierte Einkaufsliste:**
   - `CookingAssistant.suggest_recipe()` → fehlende Zutaten automatisch ermitteln
   - "Koche Lasagne" → Inventory pruefen → fehlende Zutaten auf Shopping List
   - Portionierung beruecksichtigen (4 Personen brauchen 2x Mozzarella)

3. **Kontext-Trigger:**
   - "Du verlaeesst gleich das Haus" (Presence-Tracking) + offene Einkaufsliste → Reminder
   - Wochentag-Muster: "Samstags kaufst du meistens ein"
   - Integration mit CalendarIntelligence: Termin in der Naehe vom Supermarkt

4. **Implementierungs-Ansatz:**
   - Neues Modul: `smart_shopping.py`
   - Abhaengigkeiten: `inventory.py`, `cooking_assistant.py`, `proactive.py`, `calendar_intelligence.py`
   - Redis-Keys fuer Verbrauchshistorie
   - Neuer proaktiver Trigger in `proactive.py`

---

### 2.2 Energie-Dashboard Live (Prio: HOCH)

**Status Quo:** `energy_optimizer.py` hat Backend-Logik, aber kein dediziertes Frontend. Route `energy.py` (14.462 Z.) liefert Daten.

**Verbesserungen:**

1. **Live-Dashboard-Karte im bestehenden UI:**
   - Solar-Ertrag vs. Verbrauch als Echtzeit-Gauge
   - Netz-Einspeisung/Bezug Visualisierung
   - Tages-/Wochen-/Monatsvergleich als Chart
   - Aktueller Strompreis + Prognose (wenn Tibber/aWATTar Entity vorhanden)

2. **Smarte Empfehlungen im Dashboard:**
   - "Jetzt Waschmaschine starten (Solarueberschuss: 3.2 kW)"
   - "Strom gerade 12ct/kWh — guenstiger als Durchschnitt"
   - History: Gespartes Geld durch Solar-Optimierung

3. **Implementierungs-Ansatz:**
   - Neue Dashboard-Sektion in `static/ui/app.js`
   - WebSocket fuer Live-Updates (Entity-State-Streaming via `ws_manager`)
   - Neue API-Endpoints: `/api/energy/live`, `/api/energy/forecast`
   - Chart-Library: Chart.js (leichtgewichtig, bereits im Projekt-Stil)

---

### 2.3 Multi-Room Audio Sync (Prio: MITTEL)

**Status Quo:** `follow_me.py` transferiert Musik bei Raumwechsel. `music_dj.py` empfiehlt Genres.

**Verbesserungen:**

1. **Multiroom-Grouping:**
   - "Spiel das ueberall" → `media_player.join` Service nutzen
   - "Musik nur im Wohnzimmer und Kueche" → selektives Grouping
   - "Party-Modus" → alle Speaker synchron + Volume normalisiert

2. **Intelligente Audio-Zonen:**
   - Automatisches Grouping basierend auf Praesenz (alle besetzten Raeume)
   - Separate Zonen: Kids-Zone (andere Musik), Schlafzone (leiser)
   - Uebergaenge: Wenn Person den Raum wechselt, Musik smooth ueberblenden

3. **DJ-Upgrade:**
   - "Mach lauter/leiser" kontextbezogen (welcher Raum?)
   - Playlist-Queue: "Spiel danach Jazz"
   - Stimmungswechsel: "Wechsel zu was Ruhigerem" → sanfter Genre-Uebergang

4. **Implementierungs-Ansatz:**
   - Erweiterung `follow_me.py` um Group/Ungroup Logik
   - Neues Modul: `audio_zones.py` fuer Zone-Management
   - `music_dj.py` um Queue-Management erweitern
   - Neue Function-Calls: `group_speakers`, `set_zone`, `party_mode`

---

### 2.4 Konversations-Gedaechtnis++ (Prio: MITTEL)

**Status Quo:** Memory Extractor speichert Fakten. Semantic Memory hat Embeddings. Aber: kein Projekt-Tracking, keine Meilenstein-Erkennung.

**Verbesserungen:**

1. **Projekt-Tracker:**
   - Erkennt laufende Projekte aus Konversationen ("Ich baue gerade ein Regal")
   - Status-Updates: "Wie stehts mit dem Regal?" → Jarvis erinnert sich an letzten Stand
   - Proaktiv: "Du hast seit 2 Wochen nichts zum Gartenprojekt gesagt — aufgegeben?"

2. **Persoenliche Meilensteine:**
   - Geburtstage, Jahrestage automatisch aus Kalender + Gespraechen extrahieren
   - Proaktive Glueckwuensche: "Hey, morgen ist euer Hochzeitstag!"
   - Geschenk-Erinnerungen basierend auf frueher erwaehnte Wuensche

3. **Offene-Fragen-Tracker:**
   - Wenn Jarvis etwas nicht beantworten konnte, merkt er sich die Frage
   - Spaeter proaktiv: "Uebrigens, zu deiner Frage von gestern..."
   - Web-Search (wenn aktiviert) periodisch fuer offene Fragen nutzen

4. **Implementierungs-Ansatz:**
   - Erweiterung `memory_extractor.py` um Projekt/Meilenstein-Erkennung
   - Neues Redis-Schema: `mha:projects:{name}`, `mha:milestones:{person}`
   - Neuer proaktiver Trigger: "stale_project_check"
   - ChromaDB Collection fuer Projekt-Kontext (Embeddings)

---

## 3. Verbesserungen bestehender Features

### 3.1 Schnellere Antworten (Prio: HOCH)

**Status Quo:**
- LLM Timeouts: 30-60s
- `model_router.py` unterscheidet fast/smart/deep
- Ollama `num_parallel` vermutlich auf Default (1)
- Streaming existiert bereits via WebSocket (`emit_stream_token`)

**Verbesserungen:**

1. **Streaming-First Architektur:**
   - Erste Tokens innerhalb <2s anzeigen (statt auf komplette Antwort warten)
   - Brain sollte bei jedem Request Streaming nutzen, nicht nur bei langen Antworten
   - Chunked Function-Calling: Aktionen parallel zum Streaming starten

2. **Ollama-Tuning:**
   - `num_parallel: 2` testen (RTX 3090 hat 24GB — reicht fuer 2x parallel)
   - `num_ctx` optimieren (nicht zu gross — mehr Kontext = langsamer)
   - `flash_attn: true` fuer schnellere Attention-Berechnung
   - `num_gpu: 99` sicherstellen (alles auf GPU)
   - Keep-Alive: Modell im VRAM halten (kein Cold-Start)

3. **Pre-Classifier Optimierung:**
   - Einfache Befehle ("Licht an") brauchen kein LLM — direkt Function-Call
   - `pre_classifier.py` koennte Pattern-Match vor LLM-Call machen
   - Ergebnis: <200ms fuer simple Device-Steuerung

4. **Implementierungs-Ansatz:**
   - `ollama_client.py`: Streaming-Default, `num_parallel` Config
   - `brain.py`: Stream-First mit Function-Call-Interception
   - `pre_classifier.py`: Regex-basierte Schnellroute fuer simple Befehle
   - `model_router.py`: Aggressive Downrouting fuer simple Requests
   - settings.yaml: Neue Sektion `performance:` mit Tuning-Parametern

---

### 3.2 Workshop-Modus erweitern (Prio: NIEDRIG)

**Status Quo:** `workshop_generator.py` + `workshop_library.py` generieren Lern-Inhalte. Frontend: `static/workshop/index.html` (320 KB).

**Verbesserungen:**

1. **3D-Viewer fuer STL-Dateien:**
   - Three.js STL-Loader im Workshop-Frontend
   - Rotation, Zoom, Vermessung im Browser
   - "Zeig mir das 3D-Modell vom Gehaeuse"

2. **Interaktive Schaltplaene:**
   - SVG-basierte Schaltplan-Darstellung
   - Klickbare Komponenten mit Tooltip (Werte, Datenblatt-Links)
   - Export als SVG/PNG

3. **BOM-Export:**
   - CSV-Export fuer Bestelllisten (Reichelt, Mouser Format)
   - PDF-Export mit Stueckliste + Schaltplan
   - Automatische Preisrecherche (optional, web_search noetig)

4. **Implementierungs-Ansatz:**
   - `static/workshop/`: Three.js + STLLoader einbinden
   - Neues Modul: `workshop_schematic.py` fuer Schaltplan-Generierung
   - `workshop_generator.py`: BOM-Extraction aus Projekt-Beschreibungen
   - Neue API-Endpoints: `/api/workshop/stl`, `/api/workshop/bom`

---

### 3.3 Stimm-Klonen / Custom TTS (Prio: NIEDRIG)

**Status Quo:** Piper TTS mit `thorsten-high` Voice. TTS Enhancer passt Emotion/Pausen an.

**Verbesserungen:**

1. **Custom Voice Training:**
   - Piper unterstuetzt Fine-Tuning mit eigenem Datensatz
   - ~2-5 Stunden Aufnahmen noetig (sauber, leise Umgebung)
   - Training auf RTX 3090 machbar (Piper Training Scripts)
   - Ergebnis: Eigene "Jarvis-Stimme" oder Klon einer echten Stimme

2. **Multi-Voice Setup:**
   - Verschiedene Stimmen fuer verschiedene Kontexte
   - Formell (Gaeste-Modus) vs. Casual (Alltag)
   - "Butler-Stimme" fuer besondere Anlaesse

3. **XTTS als Alternative:**
   - Coqui XTTS v2: Braucht nur 6 Sekunden Audio-Sample fuer Voice-Cloning
   - Laeuft lokal auf RTX 3090
   - Qualitaet besser als Piper, aber langsamer
   - Ideal fuer nicht-zeitkritische Ausgaben (Morning Briefing vorab generieren)

4. **Implementierungs-Ansatz:**
   - Option A (Piper Fine-Tune): Training-Pipeline, ~1 Woche Arbeit
   - Option B (XTTS): Neues TTS-Backend neben Piper, Routing nach Kontext
   - `tts_enhancer.py` erweitern um Voice-Auswahl
   - Config: `tts.voice_profiles` in settings.yaml

---

## 4. Architektur-Beobachtungen & Quick Wins

### 4.1 Bereits sehr gut geloest
- **Sicherheit:** Prompt Injection Schutz ist vorbildlich (~80 Patterns, SSRF, Trust-Levels)
- **Graceful Degradation:** Redis/ChromaDB optional, Fallbacks ueberall
- **Privacy-First:** Web Search default off, lokale LLMs, kein Cloud-Zwang
- **Modularitaet:** Klare Trennung der Concerns, jedes Feature ein eigenes Modul

### 4.2 Quick Wins (wenig Aufwand, grosser Effekt)

1. **Ollama Performance-Tuning** (~30 Min)
   - `flash_attn: true`, `num_gpu: 99`, `keep_alive: -1` in Modelfile
   - Messbar schnellere Antworten ohne Code-Aenderung

2. **Pre-Classifier Shortcut** (~2 Std)
   - Regex-Match fuer "Licht an/aus", "Temperatur auf X" → Skip LLM
   - Reduziert Latenz fuer 40% der Befehle auf <200ms

3. **Streaming Default** (~1 Std)
   - `ollama_client.py` Stream-Flag als Default
   - Gefuehlte Antwortzeit sofort besser

4. **Inventory Reminder bei Verlassen** (~2 Std)
   - `proactive.py` + Presence-Trigger: "Einkaufsliste hat 3 Eintraege"
   - Nutzt bestehendes Inventory + Proactive System

### 4.3 Technische Schulden (nicht kritisch)

- **Grosse Dateien:** `automation_engine.py` (117K Z.), `pattern_engine.py` (105K Z.), `models.py` (99K Z.) — schwer zu reviewen, aber funktional
- **Repair Planner Stub:** `repair_planner.py:1227` hat einen Roboterarm-Stub — entweder implementieren oder entfernen
- **Zwei Server-Setup:** Addon (Flask) + Assistant (FastAPI) — langfristig konsolidieren?

---

## 5. Empfohlene Reihenfolge

| Prio | Feature | Aufwand | Impact |
|------|---------|---------|--------|
| 1 | Ollama Performance-Tuning (Quick Win) | 30 Min | Sofort schnellere Antworten |
| 2 | Streaming Default (Quick Win) | 1 Std | Gefuehlt 3x schneller |
| 3 | Pre-Classifier Shortcut (Quick Win) | 2 Std | <200ms fuer simple Befehle |
| 4 | Proaktive Einkaufsliste | 1-2 Wochen | Taeglich nuetzlich |
| 5 | Energie-Dashboard Live | 1-2 Wochen | Sichtbarer Mehrwert im UI |
| 6 | Multi-Room Audio Sync | 1 Woche | Party-Modus! |
| 7 | Konversations-Gedaechtnis++ | 2 Wochen | Jarvis wird "menschlicher" |
| 8 | Workshop-Modus erweitern | 2-3 Wochen | Nischen-Feature |
| 9 | Stimm-Klonen | 1+ Wochen | Cool, aber optional |

---

## 6. Zusammenfassung

Jarvis ist ein ausgereiftes System mit 86+ Modulen ueber 18 Entwicklungsphasen. Die Architektur ist solide, sicher und erweiterbar. Die groessten Hebel liegen in:

1. **Performance:** Ollama-Tuning + Streaming-First macht Jarvis fuehlbar schneller
2. **Proaktivitaet:** Einkaufsliste und Energie-Empfehlungen im Alltag am nuetzlichsten
3. **Erlebnis:** Multi-Room Audio und besseres Gedaechtnis machen Jarvis "magischer"

Die Quick Wins (Punkte 1-3) sollten zuerst umgesetzt werden — wenig Aufwand, grosser Effekt auf die taegliche Nutzung.
