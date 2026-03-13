# Prompt 6b: Architektur — Konflikte auflösen & Flows reparieren

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. In Prompt 6a hast du das System stabilisiert. Jetzt räumst du die Architektur auf.

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- Kann bei langem System-Prompt den Fokus auf Tool-Calls verlieren
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–6a bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke ein:
> - Prompt 1: Konflikt-Karte & Architektur-Bewertung (Konflikte A–F)
> - Prompt 3a + 3b: Flow-Analyse mit Bruchstellen & Kollisionen (13 Flows)
> - Prompt 6a: Stabilisierungs-Ergebnisse (gefixte Bugs, Memory-Status)

---

## Fokus dieses Prompts

**Drei Dinge**: Architektur-Entscheidungen treffen, Modul-Konflikte auflösen, Flows reparieren.

### Harmonisierungs-Prinzipien in diesem Prompt

- **Eine Entscheidungsinstanz**: Klare Hierarchie wenn Module gleichzeitig handeln wollen
- **Ein Flow**: Klarer Datenfluss von Input bis Output, keine Bruchstellen
- **Performance & Latenz**: Jede Architektur-Entscheidung muss Latenz berücksichtigen — Ziel: < 3 Sekunden für einfache Befehle

---

## Aufgabe

### ⚠️ Phase Gate: Regression-Check vor Start

Bevor du irgendetwas änderst:
1. **Tests ausführen**: `cd assistant && python -m pytest --tb=short -q` — Ergebnis dokumentieren
2. **Dieses Ergebnis ist die Baseline** — nach jeder Änderung in 6b müssen diese Tests weiterhin grün sein
3. Falls Tests schon fehlschlagen → zurück zu 6a, dort zuerst fixen

### Schritt 1: Architektur-Entscheidung — brain.py

Lies die Kontext-Blöcke aus Prompt 1. Entscheide:

| Option | Was | Wann wählen |
|---|---|---|
| **A: Refactoring** | brain.py aufräumen, klare Methoden-Zuständigkeiten | Wenn brain.py grundsätzlich richtig ist, nur zu groß |
| **B: Event-Bus** | Module kommunizieren über Events | Wenn viele Module unkoordiniert interagieren |
| **C: Pipeline** | Input → Processing → Output als klarer Datenfluss | Wenn der Flow das Hauptproblem ist |
| **D: Mediator** | brain.py als schlanker Vermittler, Logik in Modulen | Wenn brain.py zu viel Logik enthält |

> **Wähle die Option mit minimalem Umbau und maximalem Effekt.** Over-Engineering vermeiden.

#### Konkrete Analyse vor dem Refactoring

> ⚠️ **brain.py hat 10.000+ Zeilen.** Bevor du refactorst, verstehe die Struktur:

1. **Read** — brain.py in Abschnitten lesen (offset 1/2001/4001/6001/8001/10001)
2. **Grep** — Welche Methoden hat brain.py? `pattern="async def |def " path="assistant/assistant/brain.py" output_mode="count"`
3. **Grep** — Wer importiert brain.py? `pattern="from.*brain import|import brain" path="assistant/"`
4. Identifiziere die **logischen Blöcke** in brain.py:
   - Request-Verarbeitung (Chat-Handling)
   - LLM-Kommunikation (Ollama-Calls)
   - Function-Calling-Loop
   - Memory-Management
   - Proaktive-Logik
   - Routinen-Handling
5. **Entscheide pro Block**: Kann er in ein eigenes Modul extrahiert werden OHNE die Tests zu brechen?

**Wichtig**: Refactore **schrittweise** — ein Block nach dem anderen, Tests nach jedem Schritt. NICHT alles auf einmal umbauen.

**Implementiere die gewählte Option:**
1. **Edit** — Einen Block extrahieren
2. **Bash** — Tests: `cd assistant && python -m pytest -x`
3. **Git** — Committen wenn Tests grün: `git commit -m "Refactor: [Block] aus brain.py extrahiert"`
4. Nächsten Block extrahieren, wiederholen

### Schritt 2: Modul-Konflikte auflösen (Konflikte A–F aus Prompt 1)

Für jeden Konflikt aus der Konflikt-Karte:

#### Konflikt A: Wer bestimmt was Jarvis SAGT?
- Klare Zuständigkeit: `context_builder.py` baut den Prompt, `personality.py` liefert den Charakter
- Keine anderen Module dürfen den Prompt direkt modifizieren

#### Konflikt B: Wer bestimmt was Jarvis TUT?
- Hierarchie implementieren: `User-Befehl > Routine > Proaktiv > Autonom`
- `conflict_resolver.py` muss in den Flow integriert sein (nicht nur existieren)

#### Konflikt C: Wer bestimmt was Jarvis WEISS?
- (Bereits in 6a adressiert durch Memory-Fix)

#### Konflikt D: Wie Jarvis KLINGT
- (Wird in 6c adressiert — Persönlichkeit)

#### Konflikt E: Timing & Prioritäten
- Priority-Queue oder Lock-Mechanismus für gleichzeitige Aktionen
- Regel: User-Aktion hat IMMER Vorrang

#### Konflikt F: Assistant ↔ Addon Interaktion — Vorab-Check (Pflicht!)

> ⚠️ **Bevor** du in Schritt 1 die Architektur umbauen darfst, musst du prüfen ob Addon davon betroffen ist.
> Die eigentliche Addon-Koordination kommt in 6d — aber hier musst du sicherstellen, dass deine Architektur-Änderungen die Addon-Schnittstelle **nicht brechen**.

**Pflicht-Check vor Architektur-Änderungen:**
1. **Grep** — Wo ruft der Addon den Assistant auf? `pattern="assistant|api/chat|api/assistant" path="addon/rootfs/opt/mindhome/"`
2. **Grep** — Wo ruft der Assistant den Addon auf? `pattern="addon|127\.0\.0\.1:8200" path="assistant/assistant/"`
3. **Grep** — Shared Schemas: `pattern="from shared|import shared" path="assistant/" path="addon/"`
4. Dokumentiere die **Schnittstellen-Punkte** (API-Endpoints, Shared-Schemas, Redis-Keys)
5. **Regel**: Keine Architektur-Änderung darf diese Schnittstellen-Punkte brechen, ohne dass ein Migrations-Plan für den Addon existiert

**Output in Kontext-Block:**
```
### Addon-Kompatibilitäts-Check (Pflicht vor Architektur-Umbau)
- Schnittstellen: [Liste der API-Endpoints/Redis-Keys die Addon nutzt]
- Von Architektur-Änderung betroffen: Ja/Nein
- Falls Ja: Migrations-Plan für Addon: [...]
```

**Für jeden Konflikt:**
1. Lies die beteiligten Module mit **Read**
2. Prüfe mit **Grep** wo die Konflikte auftreten
3. Implementiere die Lösung mit **Edit**
4. Verifiziere mit **Bash** (Tests)

### Schritt 3: Flows reparieren (aus Prompt 3a/3b)

Arbeite die **Bruchstellen** aus der Flow-Analyse ab. Priorität:

1. **Flow 1** (Sprach-Input → Antwort) — der Haupt-Flow muss fehlerfrei sein
2. **Flow 2** (Proaktive Benachrichtigung) — zweithäufigster Pfad
3. **Flow 4** (Autonome Aktion) — Sicherheitsrelevant (Autonomie-Limits!)
4. **Flow 11** (Boot-Sequenz) — muss robust starten
5. Alle weiteren Flows nach Severity der Bruchstellen

**Für jede Bruchstelle:**
- Dokumentiere was kaputt ist (Datei:Zeile)
- Implementiere den Fix
- Prüfe ob andere Flows davon betroffen sind

### Schritt 4: Performance-Optimierungen (aus Prompt 4c, Fehlerklasse 13)

Basierend auf den Performance-Findings aus Prompt 4c:

**Die drei wirkungsvollsten Optimierungen:**

1. **Sequentielle → Parallele Async-Calls**: Überall wo unabhängige `await`s nacheinander stehen → `asyncio.gather()` nutzen. Besonders in `brain.py` und `context_builder.py`.

2. **LLM-Calls reduzieren**: Prüfe ob pro User-Request mehrere LLM-Calls gemacht werden (Pre-Classifier, Mood-Detection, Haupt-Antwort, Memory-Extraction). Kann etwas davon ohne LLM-Call gelöst werden oder in einen einzigen Call zusammengefasst werden?

3. **Model-Routing optimieren**: Einfache Befehle ("Licht an") zum schnellsten Modell routen. Nicht alles über das größte Modell laufen lassen.

**Verifikation:**
```
# Vorher/Nachher: Wie viele await-Calls sind jetzt parallelisiert?
Grep: pattern="asyncio\.gather" path="assistant/assistant/" output_mode="count"
```

### Schritt 5: 🟠 HOHE Bugs fixen (aus Prompt 4a–4c)

Features die nicht funktionieren aber nicht crashen. Arbeite die 🟠-Bug-Liste ab.

---

## Output-Format

### 1. Architektur-Entscheidung

| Entscheidung | Gewählt | Begründung | Geänderte Dateien |
|---|---|---|---|
| brain.py | ? | ? | ? |
| Priority-System | ? | ? | ? |

### 2. Konflikt-Lösungen

Für jeden Konflikt (A, B, E):
```
### Konflikt [X]: Kurzbeschreibung
- **Lösung**: Was implementiert wurde
- **Geänderte Dateien**: Liste
- **Verifikation**: Wie geprüft
```

### 3. Flow-Fixes

| Flow | Bruchstelle | Fix | Status |
|---|---|---|---|
| 1: Sprach-Input | datei.py:123 — Beschreibung | Was gefixt | ✅/❌ |
| ... | ... | ... | ... |

### 4. 🟠 Bug-Fixes

Für jeden gefixten Bug:
```
### 🟠 Bug #X: Kurzbeschreibung
- **Datei**: path:zeile
- **Fix**: Was geändert
- **Tests**: ✅/❌
```

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

> **Jeder Fix muss VERIFIZIERT sein.** Read → Grep → Edit → Grep → Bash (Tests). Keine Abkürzungen.

- **Architektur-Entscheidung ZUERST** — bevor Konflikte gelöst werden
- **Konflikte A, B, E in diesem Prompt** — D und F in 6c/6d
- **Flows nach Priorität** — wenn die Zeit knapp wird: Flow 1 und 2 sind Pflicht
- **Tests nach jedem Fix** — `python -m pytest -x`
- **Keine Persönlichkeits-Änderungen hier** — das kommt in 6c
- **⚠️ Rollback-Regel**: Wenn eine Architektur-Änderung Tests bricht die in P6a grün waren, hast du drei Optionen: **(a)** den Architektur-Fix so anpassen dass P6a-Fixes erhalten bleiben, **(b)** die P6a-Fixes an die neue Architektur anpassen (bevorzugt), **(c)** die Architektur-Änderung verwerfen. Dokumentiere im Output welche P6a-Fixes angepasst werden mussten und warum.

### ⚠️ Phase Gate: Checkpoint am Ende von 6b

Bevor du zu 6c übergehst:
1. **Alle Tests laufen lassen**: `cd assistant && python -m pytest --tb=short -q`
2. **Vergleiche mit 6a-Baseline**: Sind alle Tests die nach 6a grün waren immer noch grün?
3. **Git-Tag setzen**: `git tag checkpoint-6b`
4. Falls Tests schlechter als nach 6a → Problem identifizieren und fixen bevor du weitergehst

---

## Erfolgs-Kriterien

- □ Architektur-Konflikte aufgeloest
- □ Performance-Optimierungen verifiziert
- □ Kein ImportError

## ⚡ Übergabe an Prompt 6c

```
## KONTEXT AUS PROMPT 6b: Architektur

### Architektur-Entscheidung
[brain.py → Option X, Priority-System → Beschreibung]

### Gelöste Konflikte
[A → Lösung, B → Lösung, E → Lösung]

### Reparierte Flows
[Flow-Nr → Was gefixt → Status]

### Gefixte 🟠 Bugs
[Bug-# → Datei → Was gefixt]

### Offene Punkte für 6c/6d
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
