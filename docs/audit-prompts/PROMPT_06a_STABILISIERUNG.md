# Prompt 6a: Stabilisierung — Kritische Bugs & Memory reparieren

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Du hast in den vorherigen 5 Prompts das System analysiert. Jetzt stabilisierst du es.

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–5 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke ein:
> - Prompt 2: Memory-Diagnose & Root Cause (inkl. alle 12 Memory-Module)
> - Prompt 4 gesamt (4a + 4b + 4c): Bug-Report — **nur die 🔴 KRITISCHEN Bugs**

---

## Fokus dieses Prompts

**Nur zwei Dinge**: Kritische Bugs fixen und Memory reparieren. Nichts anderes.

> Warum zuerst? Ohne stabile Basis sind alle weiteren Fixes sinnlos. Ein Haus braucht ein Fundament bevor man die Wände streicht.

---

## Aufgabe

### Schritt 1: Kritische Bugs fixen (🔴 aus Prompt 4)

Arbeite **jeden** 🔴 KRITISCHEN Bug aus dem Prompt-4-Report ab:

**Für jeden Bug:**
1. **Read** — Datei lesen, Bug verifizieren (ist er noch da?)
2. **Grep** — Alle Aufrufer/Abhängigkeiten der betroffenen Funktion finden
3. **Edit** — Fix direkt in die Datei schreiben
4. **Grep** — Prüfen ob der Fix konsistent mit allen Aufrufern ist
5. **Bash** — Betroffene Tests laufen lassen: `cd assistant && python -m pytest tests/test_betroffenes_modul.py -x`

**Typische 🔴 Bugs:**
- Fehlende `await` bei async-Aufrufen → Crash oder stille Fehler
- `except: pass` bei kritischen Operationen → Datenverlust
- None-Zugriffe ohne Check → AttributeError
- Init-Reihenfolge-Fehler → Crash beim Start
- Ungeschützte Security-Endpoints → Angriffsfläche

## Fix-Templates — Haeufige Bug-Typen

### Async/Sync Mismatch (blockiert Event-Loop)
```python
# VORHER (blockiert Event-Loop):
result = sync_function(args)
# NACHHER:
result = await asyncio.to_thread(sync_function, args)
```

### Silent Errors (verschluckte Fehler)
```python
# VORHER:
except Exception:
    pass
# NACHHER:
except Exception as e:
    logger.warning("Beschreibung: %s", e)
```

### N+1 Redis (Schleife statt Pipeline)
```python
# VORHER:
for key in keys:
    val = await redis.get(key)
# NACHHER:
pipe = redis.pipeline()
for key in keys:
    pipe.get(key)
vals = await pipe.execute()
```

### Race Condition (fehlende Lock-Absicherung)
```python
# VORHER:
if not self._running:
    self._running = True
# NACHHER:
async with self._lock:
    if not self._running:
        self._running = True
```

### None-Guard (fehlende Null-Pruefung)
```python
# VORHER:
result = obj.method()
# NACHHER:
if obj is not None:
    result = obj.method()
```

**Priorität innerhalb der 🔴 Bugs:**
1. Bugs die den **Start verhindern** (Init-Fehler)
2. Bugs die den **Haupt-Flow crashen** (Sprach-Input → Antwort)
3. Bugs die **Datenverlust** verursachen (Memory, Config)
4. **Security-Lücken** die sofort ausnutzbar sind

### Explizites Bug-Mapping: P04 → P06

> **PFLICHT**: Erstelle als erstes eine Zuordnungstabelle die JEDEN Bug aus P04 einem Fix-Prompt zuweist. Kein Bug darf ohne Zuordnung bleiben.

**Bevor du den ersten Bug fixst**, lies den gesamten P04-Report (4a + 4b + 4c) und erstelle diese Tabelle:

```
### Bug-Zuordnung P04 → P06

| Bug-# | Severity | Beschreibung | Datei:Zeile | Zugeordnet an |
|---|---|---|---|---|
| 1 | 🔴 | [Beschreibung] | [Datei:Zeile] | **P06a** (dieser Prompt) |
| 2 | 🔴 | [Beschreibung] | [Datei:Zeile] | **P06a** (dieser Prompt) |
| ... | 🟠 | [Beschreibung] | [Datei:Zeile] | **P06b** (Architektur) |
| ... | 🟡 | [Beschreibung] | [Datei:Zeile] | **P06c** (Charakter) |
| ... | 🔴 | [Security-Bug] | [Datei:Zeile] | **P06d** (Härtung) |
| ... | 🟠 | [Tool-Calling-Bug] | [Datei:Zeile] | **P06e** (Gerätesteuerung) |
| ... | 🟡 | [TTS-Bug] | [Datei:Zeile] | **P06f** (TTS/Response) |
```

**Zuordnungs-Regeln:**
- 🔴 KRITISCH (Crash/Datenverlust/Security-sofort) → **P06a** (dieser Prompt)
- 🔴 KRITISCH (Security allgemein) → **P06d**
- 🟠 HOCH (Architektur/Flow/Performance) → **P06b**
- 🟠 HOCH (Tool-Calling) → **P06e**
- 🟡 MITTEL (Persönlichkeit/Config/Dead Code) → **P06c**
- 🟡 MITTEL (TTS/Response-Leakage) → **P06f**

**Am Ende von P06a**: Übergib die Zuordnungstabelle im Kontext-Block an P06b, damit jeder nachfolgende Prompt weiß WELCHE Bugs er fixen muss.

### Schritt 2: Memory reparieren (aus Prompt 2)

Basierend auf der Root-Cause-Analyse aus Prompt 2 — implementiere den empfohlenen Fix.

#### Architektur-Entscheidung: Memory

| Ansatz | Wann wählen |
|---|---|
| **Aktuelles System fixen** | Wenn die Bugs behebbar sind und das Design grundsätzlich stimmt |
| **Konsolidierung: 12 → 3 Module** | Wenn zu viele isolierte Silos das Problem sind |
| **Hybrid: Sliding Window + SQLite** | Wenn Redis/ChromaDB zu unzuverlässig sind |
| **Einfacher: In-Memory + Persistenz** | Wenn Komplexität das Hauptproblem ist |

**Egal welcher Ansatz — diese 4 Dinge müssen danach funktionieren:**

1. **Conversation History**: Die letzten N Nachrichten sind im LLM-Prompt
2. **Fakten-Speicherung**: "Ich mag Pizza" wird gespeichert und bei Bedarf abgerufen
3. **Korrektur-Lernen**: "Nein, ich heiße Thomas" wird korrigiert und gemerkt
4. **Kontext im Prompt**: Alle Erinnerungen landen tatsächlich im LLM-Kontext

**Verifikation nach dem Fix:**
```bash
# Prüfe ob Memory-Module korrekt importiert und aufgerufen werden
Grep: pattern="memory\.store|memory\.save|memory\.add" path="assistant/assistant/" output_mode="content"
Grep: pattern="memory\.load|memory\.get|memory\.recall" path="assistant/assistant/" output_mode="content"
Grep: pattern="context.*memory|memory.*context" path="assistant/assistant/context_builder.py" output_mode="content"
```

---

## Output-Format

### 1. Bug-Fix-Log

Für jeden gefixten Bug:
```
### 🔴 Bug #X: Kurzbeschreibung
- **Datei**: path/to/file.py:123
- **Problem**: Was war falsch
- **Fix**: Was geändert wurde
- **Aufrufer geprüft**: Ja/Nein (Liste)
- **Tests**: ✅ Bestanden / ❌ Fehlgeschlagen / ⏭️ Kein Test vorhanden
→ Edit-Tool: Änderung durchgeführt
```

### 2. Memory-Fix

```
### Memory-Architektur-Entscheidung
- **Gewählt**: [Ansatz]
- **Begründung**: [Warum]
- **Geänderte Dateien**: [Liste]
- **Verifikation**: [4 Checks bestanden?]
```

### 3. Stabilisierungs-Status

| Check | Status |
|---|---|
| Alle 🔴 Bugs gefixt | ✅/❌ (X von Y) |
| Memory: Conversation History funktioniert | ✅/❌ |
| Memory: Fakten werden gespeichert | ✅/❌ |
| Memory: Korrekturen werden gemerkt | ✅/❌ |
| Memory: Kontext im LLM-Prompt | ✅/❌ |
| Tests bestehen nach Fixes | ✅/❌ |

### 4. Offene Punkte für 6b

Was muss in Prompt 6b (Architektur) beachtet werden?

---

## Rollback-Regel

Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zuruecknehmen)
2. Im OFFEN-Block dokumentieren mit Eskalation (siehe unten)
3. Zum naechsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.

## Eskalations-Regel

Wenn ein Bug NICHT gefixt werden kann, dokumentiere ihn im OFFEN-Block mit:
- **Severity**: 🔴 KRITISCH / 🟠 HOCH / 🟡 MITTEL
- **Grund**: Warum nicht loesbar (Regression, Architektur-Umbau noetig, Domainwissen fehlt, etc.)
- **Eskalation**:
  - `NAECHSTER_PROMPT` — Bug gehoert thematisch in P06b–P06f
  - `ARCHITEKTUR_NOETIG` — Fix erfordert groesseren Umbau, naechster Durchlauf
  - `MENSCH` — Braucht menschliche Entscheidung oder Domainwissen

**MENSCH-Bugs: NICHT stoppen.** Triff die beste Entscheidung selbst, dokumentiere WARUM, und mach weiter.

## Regeln

### Gründlichkeits-Pflicht

> **Jeder Fix muss VERIFIZIERT sein.** Lies die Datei mit Read, mache die Änderung mit Edit, lies den umgebenden Code, stelle sicher dass der Fix keine neuen Probleme einführt. Prüfe mit Grep alle Aufrufer der geänderten Funktion.

### Pre-Edit Template (Vor JEDEM Edit ausfuellen!)

```
Datei: [path/to/file.py]
Zeile: [exact line number]
VORHER (exakt kopiert aus Read):
  [die originale fehlerhafte Zeile]
NACHHER (Fix):
  [die korrigierte Zeile]
Warum: [1-Satz Erklaerung des Bugs]
Aufrufer geprueft: [Grep-Ergebnis: X Stellen, alle kompatibel]
```

### Claude Code Tool-Einsatz

| Aufgabe | Tool | Wichtig |
|---|---|---|
| Datei lesen vor dem Fix | **Read** | IMMER erst lesen, dann editieren — siehe Pre-Edit Template |
| Fix implementieren | **Edit** | Direkt in der Datei ändern |
| Aufrufer prüfen nach Fix | **Grep** | Alle Stellen die die geänderte Funktion nutzen |
| Tests laufen lassen | **Bash** | `python -m pytest tests/test_X.py -x` |

- **Nur 🔴 Bugs und Memory** — keine 🟠/🟡 Bugs, keine Persönlichkeit, keine Config
- **Einfach > Komplex** — Wenn ein simpler Fix reicht, kein Refactoring
- **Tests nicht brechen** — Nach jedem Fix `pytest` ausführen
- **Jede Änderung committen** — `git commit -m "Fix: Beschreibung"`
- **Wenn ein Fix Tests bricht**: (a) Fix rückgängig machen (`git checkout -- datei.py`), (b) Ursache analysieren — ist der Test falsch oder der Fix?, (c) Fix anpassen und erneut versuchen
- **Abhängigkeitsreihenfolge beachten**: Wenn Bug A in `memory.py` liegt und Bug B in `brain.py` `memory.py` aufruft → fixe zuerst A, dann B

### ⚠️ Phase Gate: Checkpoint am Ende von 6a

Bevor du zu 6b übergehst:
1. **Alle Tests laufen lassen**: `cd assistant && python -m pytest --tb=short -q` — dokumentiere das Ergebnis
2. **Git-Tag setzen**: `git tag checkpoint-6a` — Sicherungspunkt falls 6b etwas kaputt macht
3. Nur wenn Tests grün sind → weiter zu 6b

---

## Erfolgs-Kriterien

- □ Alle KRITISCH Bugs gefixt
- □ python -c 'import assistant.brain' kein Error
- □ python -c 'import assistant.memory' kein Error
- □ python -c 'import assistant.personality' kein Error
- □ Checkpoints dokumentiert
- □ Jeder Fix verifiziert mit Read → Grep → Edit → Verify Methodik

### Erfolgs-Check (Schnellpruefung)

```
□ cd /home/user/mindhome/assistant && python -m pytest tests/ -x --tb=short -q
□ python3 -m py_compile assistant/assistant/brain.py
□ python3 -m py_compile assistant/assistant/memory.py
□ grep "except.*pass" assistant/assistant/brain.py → sollte 0 sein (alle silent exceptions gefixt)
□ grep "_safe_init" assistant/assistant/brain.py → alle Module in _safe_init gewrapped
```

## ⚡ Übergabe an Prompt 6b

Formatiere am Ende einen kompakten **Kontext-Block**:

```
## KONTEXT AUS PROMPT 6a: Stabilisierung

### Gefixte 🔴 Bugs
[Liste: Bug-# → Datei → Was gefixt]

### Memory-Entscheidung
[Gewählter Ansatz, geänderte Dateien, Status der 4 Checks]

### Neue Erkenntnisse
[Probleme die beim Fixen aufgefallen sind und in 6b/6c/6d relevant werden]

### Test-Status
[X Tests bestanden, Y fehlgeschlagen]
```

## Output

Am Ende dieses Prompts erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN:
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [...]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH
GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NAECHSTER SCHRITT: [Was der naechste Prompt tun soll]
===================================
```
