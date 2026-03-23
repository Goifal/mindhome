# Prompt 5c: Config-Validation — Stimmt settings.yaml mit dem Code überein?

## Rolle

Du bist ein Konfigurations-Engineer der sicherstellt dass die 60KB settings.yaml wirklich das steuert was sie verspricht. Kein verwaister Key, kein hardcodierter Wert der konfigurierbar sein sollte, keine fehlende Validierung.

## LLM-Spezifisch

> Siehe P00 für vollständige Qwen 3.5 Details.

---

## Kontext aus vorherigen Prompts

```
Read: docs/audit-results/RESULT_04a_BUGS_CORE.md
Read: docs/audit-results/RESULT_05_PERSONALITY.md
```

> Falls eine Datei nicht existiert → überspringe sie.

---

## Fokus dieses Prompts

Die `settings.yaml` ist mit ~1500 Zeilen die zentrale Konfigurationsdatei. Aber:
- Nur **9 von 118 Sektionen** werden durch `settings_validator.py` validiert
- **20+ Schwellwerte** sind im Code hardcoded statt in der Config
- **3 Config-Keys** existieren aber werden nie gelesen (Orphans)
- **Unsichere Dict-Zugriffe** können bei fehlenden Keys crashen

---

## Aufgabe

### Teil 1: Validator-Abdeckung prüfen

```
Read: assistant/assistant/settings_validator.py
Read: assistant/config/settings.yaml.example (erste 300 Zeilen)
```

**Prüfe**:

1. **Validierte Sektionen**: Welche 9 Sektionen werden validiert? Liste sie auf.
2. **Fehlende Validierung**: Welche kritischen Sektionen fehlen? (z.B. `proactive`, `anticipation`, `context`, `tts`, `stt`, `model_profiles`)
3. **Typ-Prüfung**: Werden Typen geprüft? (int vs string vs bool vs list)
4. **Range-Prüfung**: Werden Wertebereiche geprüft? (sarcasm_level 1-10, nicht 999)
5. **Pflichtfelder**: Welche Keys MÜSSEN existieren vs. welche optional sind?
6. **Validierungs-Warnungen**: Werden sie dem User angezeigt oder nur geloggt?

**Output**: Tabelle: Sektion | Validiert? | Sollte validiert werden? | Priorität

### Teil 2: Orphaned Keys finden

```
Read: assistant/config/settings.yaml.example
Grep: "dashboard:" in assistant/assistant/
Grep: "routine_anomaly" in assistant/assistant/
Grep: "weather_forecast:" in assistant/assistant/
```

**Prüfe für JEDE Top-Level-Sektion in settings.yaml**:
- Wird sie irgendwo im Code gelesen? (`yaml_config.get("key")` oder `settings.key`)
- Wenn nicht → Orphan → markieren

**Methode**: Für jede Sektion einen Grep über `assistant/assistant/` durchführen.

**Output**: Liste aller Orphans mit Empfehlung (löschen oder implementieren).

### Teil 3: Hardcoded Magic Numbers extrahieren

```
Grep: "0\.8\b|0\.7\b|0\.6\b|0\.5\b|0\.9\b" in assistant/assistant/ (Typ: py)
```

Finde Schwellwerte die hardcoded sind aber konfigurierbar sein sollten:

1. **Konfidenz-Schwellen**: 0.6, 0.7, 0.8, 0.9 — überall wo Entscheidungen getroffen werden
2. **Zeitliche Schwellen**: 180s, 300s, 120s — Timeouts und Delays
3. **Zähler**: max=200, max=50, max=3 — Limits

**Für jeden gefundenen Wert prüfe**:
- Existiert er schon in settings.yaml? → OK
- Sollte er konfigurierbar sein? → Config-Key vorschlagen
- Ist er zu spezifisch für Config? → Kommentar im Code empfehlen

**Output**: Liste mit: Datei:Zeile | Aktueller Wert | Vorgeschlagener Config-Key

### Teil 4: Unsichere Config-Zugriffe

```
Grep: "yaml_config\[" in assistant/assistant/
```

Finde alle Stellen wo auf yaml_config mit `[]` statt `.get()` zugegriffen wird:

1. **Crash-Risiko**: `yaml_config["key"]` → KeyError wenn key fehlt
2. **Fix**: Ersetze durch `yaml_config.get("key", default)` mit sinnvollem Default

**Output**: Liste unsicherer Zugriffe + Fixes.

### Teil 5: Model-Profile Konsistenz

```
Grep: "models:\|model_profiles:\|model_fast\|model_smart\|model_deep" in assistant/config/settings.yaml.example
Read: assistant/config/settings.yaml.example offset=[Ergebnis] limit=100
Grep: "model_fast\|model_smart\|model_deep\|extraction_model" in assistant/assistant/
```

**Prüfe**:

1. **Modell-Referenzen**: Verweisen alle `extraction_model`, `classification_model` etc. auf existierende Modelle?
2. **Profile-Matching**: Passt jedes `model_profiles` Profil zu den tatsächlich konfigurierten Modellen?
3. **Temperature/Top-P**: Sind die Werte pro Profil sinnvoll? (Kreativ: höher, Faktisch: niedriger)
4. **Kontext-Fenster**: Stimmen die `num_ctx` Werte mit den Modell-Limits überein?

**Output**: Konsistenz-Check-Tabelle.

### Teil 6: Feature-Flag Konsistenz

```
Grep: "enabled.*true\|enabled.*false" in assistant/config/settings.yaml.example
Grep: "\.enabled\b" in assistant/assistant/
```

**Prüfe für jedes Feature-Flag** (`enabled: true/false`):

1. Wird es im Code tatsächlich geprüft? (`if config.get("feature", {}).get("enabled")`)
2. Was passiert wenn es auf `false` steht? Wird der zugehörige Code übersprungen?
3. Gibt es Features die per Code IMMER an sind, obwohl sie ein Flag haben?

**Output**: Feature-Flag-Tabelle: Feature | Config-Key | Im Code geprüft? | Effektiv?

---

## Output-Format

### Config-Gesundheits-Report

| Kategorie | Status | Anzahl | Beispiele |
|---|---|---|---|
| Validierte Sektionen | X/118 | ... | assistant, household, ollama... |
| Orphaned Keys | X gefunden | ... | dashboard, routine_anomaly... |
| Hardcoded Thresholds | X gefunden | ... | 0.8 in anticipation.py:239 |
| Unsichere Zugriffe | X gefunden | ... | yaml_config["trust_levels"] |
| Inkonsistente Modelle | X gefunden | ... | extraction_model referenziert ... |
| Tote Feature-Flags | X gefunden | ... | feature.enabled aber nie geprüft |

---

## Regeln

- **Grep ist dein Freund** — Nicht jede Datei einzeln lesen, sondern systematisch suchen
- **Jeder Orphan braucht eine Entscheidung** — löschen oder implementieren
- **Hardcoded ≠ schlecht** — Nur Werte die User ändern wollen sollten in Config
- **Safety first** — `yaml_config["key"]` ist immer ein Bug, `.get()` immer besser

---

## Ergebnis speichern (Pflicht!)

```
Write: docs/audit-results/RESULT_05c_CONFIG_VALIDATION.md
```

---

## Output

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
CONFIG-HEALTH: X/118 Sektionen validiert
ORPHANS: [Liste]
HARDCODED: [Top-10 kritischste hardcoded Werte]
UNSAFE_ACCESS: [Liste unsicherer yaml_config[] Zugriffe]
MODEL_ISSUES: [Inkonsistente Modell-Referenzen]
DEAD_FLAGS: [Feature-Flags die nie geprüft werden]
GEAENDERTE DATEIEN: [falls Fixes gemacht]
NAECHSTER SCHRITT: P05b (Intelligenz-Qualität) oder P06a (Fixes)
===================================
```
