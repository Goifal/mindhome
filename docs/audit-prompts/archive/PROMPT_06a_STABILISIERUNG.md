# Prompt 6a: Stabilisierung — Kritische Bugs & Memory reparieren

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Du hast in den vorherigen 5 Prompts das System analysiert. Jetzt stabilisierst du es.

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

**Priorität innerhalb der 🔴 Bugs:**
1. Bugs die den **Start verhindern** (Init-Fehler)
2. Bugs die den **Haupt-Flow crashen** (Sprach-Input → Antwort)
3. Bugs die **Datenverlust** verursachen (Memory, Config)
4. **Security-Lücken** die sofort ausnutzbar sind

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

## Regeln

### Gründlichkeits-Pflicht

> **Jeder Fix muss VERIFIZIERT sein.** Lies die Datei mit Read, mache die Änderung mit Edit, lies den umgebenden Code, stelle sicher dass der Fix keine neuen Probleme einführt. Prüfe mit Grep alle Aufrufer der geänderten Funktion.

### Claude Code Tool-Einsatz

| Aufgabe | Tool | Wichtig |
|---|---|---|
| Datei lesen vor dem Fix | **Read** | IMMER erst lesen, dann editieren |
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
