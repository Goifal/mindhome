# Prompt 6c: Charakter — Persönlichkeit harmonisieren & Config aufräumen

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. In 6a hast du stabilisiert, in 6b die Architektur aufgeräumt. Jetzt machst du Jarvis zu **einem** Charakter.

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–6b bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke ein:
> - Prompt 5: Persönlichkeits-Audit & Config-Analyse (MCU-Score, Inkonsistenzen, Config-Probleme)
> - Prompt 4 gesamt (4a + 4b + 4c): Bug-Report — die 🟡 MITTLEREN Bugs
> - Prompt 6b: Architektur-Ergebnisse (gelöste Konflikte, reparierte Flows)

---

## Fokus dieses Prompts

**Drei Dinge**: Persönlichkeit vereinheitlichen, Config-Fehler fixen, mittlere Bugs beheben.

### Harmonisierungs-Prinzipien in diesem Prompt

- **Eine Stimme**: Alle Antwort-Pfade durch dieselbe Persönlichkeits-Pipeline
- **Ein Charakter**: Gleicher Jarvis ob Frage, Warnung oder Briefing
- **Ein Flow** (Feinschliff): 🟡 Bugs fixen, Dead Code entfernen

---

## Aufgabe

### ⚠️ Phase Gate: Regression-Check vor Start

1. **Tests ausführen**: `cd assistant && python -m pytest --tb=short -q`
2. **Vergleiche mit 6b-Checkpoint**: Alle Tests noch grün?
3. Falls Tests fehlschlagen → zurück zu 6b, dort fixen

### Schritt 1: System-Prompt optimieren (aus Prompt 5)

Lies `personality.py` — besonders `SYSTEM_PROMPT_TEMPLATE` und `build_system_prompt()`.

**Implementiere die Verbesserungen aus Prompt 5:**
1. **MCU-Authentizität erhöhen**: Klingt der Prompt wie der echte Jarvis?
2. **Token-Effizienz**: Überflüssige Anweisungen kürzen
3. **Klarheit**: Widersprüchliche Anweisungen auflösen
4. **Overloading reduzieren**: Prompt fokussieren, nicht alles reinpacken

> **Regel**: Kürzer ist oft besser. Jede Zeile im System-Prompt kostet Token die für Memory und Kontext fehlen.

### Schritt 2: Persönlichkeits-Konsistenz herstellen (Konflikt D aus Prompt 1)

**Alle Antwort-Pfade müssen durch dieselbe Persönlichkeits-Pipeline:**

| Pfad | Soll-Zustand | Prüfen |
|---|---|---|
| Normale Antwort | Durch `personality.py` → `context_builder.py` | ✅ Standard-Pfad |
| Proaktive Warnung (`proactive.py`) | Durch dieselbe Pipeline | Hat eigene Templates? |
| Morgen-Briefing (`routine_engine.py`) | Durch dieselbe Pipeline | Hat eigene Templates? |
| Fehler-Meldung | Durch dieselbe Pipeline | Oder hardcoded Strings? |
| Function-Call-Bestätigung | Durch dieselbe Pipeline | "Licht ist an" — Jarvis-Ton? |
| Autonome Aktion | Durch dieselbe Pipeline | Oder eigene Formulierung? |

**Für jeden Pfad der die Pipeline umgeht:**
1. **Read** — Das Modul lesen, eigene Templates finden
2. **Grep** — `pattern="system_prompt|SYSTEM_PROMPT|template" path="assistant/assistant/proactive.py"` etc.
3. **Edit** — Eigene Templates entfernen, durch Pipeline-Aufruf ersetzen
4. **Bash** — Tests laufen lassen

## Banned Phrases fuer Qwen 3.5

Diese Floskeln MUESSEN in brain.py _filter_response gefiltert werden:
- "Natuerlich!"
- "Gerne!"
- "Selbstverstaendlich!"
- "Kann ich dir noch etwas helfen?"
- "Kann ich sonst noch etwas tun?"
- "Ich schalte jetzt"
- "Ich werde jetzt"

Pruefe mit: `grep "banned_phrases\|banned_starters" brain.py`

### Schritt 3: Config aufräumen (aus Prompt 5)

Arbeite die Config-Audit-Ergebnisse aus Prompt 5 ab:

**3a) Unbenutzte Config-Werte entfernen:**
Für jeden Wert in `settings.yaml` der laut Prompt 5 nicht im Code genutzt wird:
```
Grep: pattern="KEY_NAME" path="assistant/" output_mode="files_with_matches"
```
Wenn 0 Treffer → Wert entfernen oder dokumentieren warum er existiert.

**3b) Fehlende Config-Werte hinzufügen:**
Code der auf Config-Werte zugreift die nicht in `settings.yaml` stehen → Default-Werte in YAML dokumentieren.

**3c) YAML-Dateien korrekt laden:**
Prüfe ob `easter_eggs.yaml`, `opinion_rules.yaml`, `humor_triggers.yaml`, `room_profiles.yaml`, `automation_templates.yaml`, `entity_roles_defaults.yaml`, `maintenance.yaml` alle korrekt geladen werden.

**3d) Addon-Config-Überlappung:**
Prüfe ob `addon/config.yaml` und `assistant/config/settings.yaml` sich widersprechen.

### Schritt 4: 🟡 Mittlere Bugs fixen (aus Prompt 4)

Logik-Fehler, fehlende Integrationen, Inkonsistenzen. Arbeite die 🟡-Bug-Liste ab.

### Schritt 5: Dead Code entfernen

Module oder Funktionen die laut Prompt 4 (Dead-Code-Liste) nie aufgerufen werden:
- **Grep** um zu verifizieren: `pattern="modul_name|funktion_name" path="assistant/"` → 0 Treffer
- Wenn tatsächlich Dead Code: Entfernen oder als deprecated markieren
- **Vorsicht**: Manche Module werden dynamisch geladen — Grep prüft nur statische Imports

---

## Output-Format

### 1. System-Prompt-Änderungen

```
### System-Prompt Optimierung
- **Token vorher**: ~X
- **Token nachher**: ~Y
- **Geändert**: [Was und warum]
- **MCU-Score vorher**: X/10
- **MCU-Score nachher**: Y/10
```

### 2. Persönlichkeits-Fixes

| Pfad | Problem | Fix | Datei:Zeile |
|---|---|---|---|
| Proaktive Warnung | Eigene Templates | Pipeline-Aufruf | proactive.py:123 |
| ... | ... | ... | ... |

### 3. Config-Bereinigung

| Config-Datei | Entfernt | Hinzugefügt | Korrigiert |
|---|---|---|---|
| settings.yaml | X Werte | Y Werte | Z Werte |
| ... | ... | ... | ... |

### 4. 🟡 Bug-Fixes

```
### 🟡 Bug #X: Kurzbeschreibung
- **Datei**: path:zeile
- **Fix**: Was geändert
- **Tests**: ✅/❌
```

### 5. Dead Code entfernt

| Modul/Funktion | Grund | Verifiziert mit Grep |
|---|---|---|
| ? | Nie aufgerufen | 0 Treffer für "X" |

---

## Rollback-Regel

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren: "Fix X verursacht Regression Y"
3. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

## Regeln

### Gründlichkeits-Pflicht

> **Lies `personality.py` KOMPLETT mit Read. Lies JEDE YAML-Config mit Read. Prüfe JEDEN Config-Wert mit Grep.**

- **Persönlichkeit ist Kern-Feature** — nicht "nice to have"
- **Config-Werte immer mit Grep verifizieren** — nicht nur YAML lesen
- **Dead Code nur entfernen wenn Grep 0 Treffer zeigt**
- **Tests nach jedem Fix**
- **Keine Security/Resilience hier** — das kommt in 6d
- **⚠️ System-Prompt-Änderungen**: Bevor du Anweisungen im System-Prompt kürzst, prüfe ob ein P6a/6b-Fix davon abhängt. Keine Anweisungen entfernen die ein Bug-Fix eingeführt hat!

### ⚠️ Phase Gate: Checkpoint am Ende von 6c

1. **Alle Tests laufen lassen**: `cd assistant && python -m pytest --tb=short -q`
2. **Git-Tag setzen**: `git tag checkpoint-6c`

---

## Erfolgs-Kriterien

- □ MCU-Score >= 7/10
- □ System-Prompt unter 800 Tokens Basis
- □ Floskeln in banned_phrases

## ⚡ Übergabe an Prompt 6d

```
## KONTEXT AUS PROMPT 6c: Charakter

### System-Prompt
[Token-Änderung, MCU-Score-Änderung, wichtigste Änderungen]

### Persönlichkeits-Fixes
[Welche Pfade jetzt durch die Pipeline gehen]

### Config-Status
[Was bereinigt wurde, was noch offen ist]

### Gefixte 🟡 Bugs
[Bug-# → Datei → Was gefixt]

### Entfernter Dead Code
[Liste]

### Offene Punkte für 6d
[Was noch fehlt]
```

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN: [Liste der nicht gefixten Issues mit Grund]
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
