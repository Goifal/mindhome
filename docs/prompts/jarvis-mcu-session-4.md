# Session 4: J.A.R.V.I.S. MCU vs. MindHome — Roadmap & Sprint-Plan

> **Verwendung:** Diesen Prompt an Claude Code geben. NUR Session 4 ausführen — danach stoppen.
> **Scope:** NUR den Assistenten (`assistant/` Verzeichnis). Alle Sprints und Aufgaben beziehen sich auf den Assistenten-Code.
> **Voraussetzung:** Session 1-3 müssen abgeschlossen sein. Die Plan-Datei muss alle 12 Kategorien enthalten.
> **Ergebnis:** Roadmap mit Sprints und Implementierungsanweisungen in `docs/prompts/jarvis-mcu-implementation-plan.md`

---

## Deine Aufgabe

Du bist ein Elite-Software-Architekt. Die vorherigen 3 Sessions haben alle 12 Kategorien analysiert. **Dein Job ist die Roadmap.**

**Dies ist Session 4 von 5.** Du erstellst:
1. Abhängigkeitsgraph
2. Sprint-Plan mit konkreten Aufgaben
3. Detaillierte Implementierungsanweisungen für jede Aufgabe
4. Gesamtübersicht mit gewichtetem Score
5. Quick Wins, Fazit, Schutzliste

### Durchlauf-Nummer ermitteln
Lies den **Changelog** am Ende von `docs/prompts/jarvis-mcu-implementation-plan.md`. Zähle die bestehenden Durchlauf-Einträge. Dein Durchlauf ist **der nächste**. Beim allerersten Durchlauf (kein Changelog vorhanden) bist du `#1`.

### Vorbereitung
1. **Lies die komplette Plan-Datei** — verstehe alle 12 Kategorien-Analysen
2. Identifiziere alle Verbesserungsvorschläge aus allen Kategorien
3. Erstelle daraus die Roadmap

---

## Regeln

### Regel 1: Anweisungen müssen Copy-Paste-fähig sein
Jede Aufgabe muss so konkret sein, dass ein Code-Agent (oder Entwickler) sie **ohne Rückfragen** umsetzen kann. Keine vagen Formulierungen wie "verbessere die Logik" — sondern "füge in `anticipation.py` Zeile 340 eine Gewichtung hinzu die den Wochentag berücksichtigt".

### Regel 2: Code-Referenzen verifizieren
Für jede Aufgabe: **lies die referenzierte Datei/Funktion** und prüfe dass sie existiert und die Zeilenangabe stimmt. Keine Aufgabe ohne verifizierte Code-Referenz.

### Regel 3: Schutzliste respektieren
Kein Sprint-Task darf ein "Besser als MCU" Feature beschädigen. Prüfe jede Aufgabe explizit dagegen.

### Regel 4: Kontext-Limit-Strategie
- Nie ganze Dateien laden — Grep nutzen, dann gezielt lesen (50-100 Zeilen)
- Sprints sequentiell ausarbeiten — nicht alle gleichzeitig im Kontext halten
- Nach jedem Sprint sofort in die Plan-Datei schreiben

---

## Phase 2: Abhängigkeitsgraph & Sprint-Plan

### Abhängigkeitsgraph
Welche Verbesserungen müssen VOR anderen umgesetzt werden?
```
[Feature A] ──→ [Feature B] ──→ [Feature C]
                                 ↗
[Feature D] ────────────────────┘
```

### Sprint-Plan Sortierung
1. **Abhängigkeiten zuerst** — Fundamente vor Features die darauf aufbauen
2. **Höchster Impact zuerst** — Was den Gesamt-Score am meisten hebt (Gewicht × Prozent-Gewinn)
3. **Quick Wins vorziehen** — Kleine Änderungen mit großem Effekt vor Großprojekten
4. **Risiko minimieren** — Sicherheitskritische Verbesserungen vor Nice-to-haves
5. **Vernetzung maximieren** — Features die andere Features besser machen zuerst

Format pro Sprint:
```
### Sprint X: [Thema]
**Status:** [ ] Offen | [~] In Arbeit | [x] Abgeschlossen
**Ziel:** [Was MCU-Level sein soll nach diesem Sprint]
**Vorher → Nachher:** XX% → XX% (Ziel)
**Betroffene Dateien:** [Vollständige Liste]

[Aufgaben...]

### Sprint X — Validierung
- [ ] Alle Aufgaben abgeschlossen
- [ ] `python -m pytest --tb=short -q` — alle Tests grün
- [ ] `ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/` — kein Fehler
- [ ] Kein Breaking Change
- [ ] Schutzliste geprüft
```

---

## Phase 3: Implementierungsanweisungen

Für **jede einzelne Aufgabe** in den Sprints:

```
### Aufgabe X.Y: [Titel]
**Status:** [ ] Offen
**Sprint:** X | **Priorität:** [Kritisch/Hoch/Mittel] | **Aufwand:** [Klein/Mittel/Groß]

#### Ist-Zustand
- Datei: `vollständiger/pfad/zur/datei.py`
- Aktuelle Implementierung: [Was der Code jetzt tut, mit Zeilenreferenz]
- Problem: [Was fehlt oder schlecht ist]

#### Soll-Zustand (MCU-Level)
- [Genau beschreiben wie es nach der Änderung funktionieren soll]
- [Konkretes Verhalten das der MCU-Jarvis zeigt und das erreicht werden soll]

#### Implementierungsschritte
1. In `datei.py`, Funktion `xyz()`: [Was genau zu ändern ist]
2. Neue Methode `abc()` erstellen die: [Logik beschreiben]
3. In `brain.py` einbinden: [Wo und wie aufrufen]
4. In `settings.yaml`: [Welche Config-Optionen hinzufügen]

#### Verknüpfungen
- Muss aufgerufen werden in: `datei.py`, Funktion `xyz()`
- Benötigt Config in: `settings.yaml`, Sektion `abc`
- Beeinflusst: [Welche anderen Module/Features]

#### Akzeptanzkriterien
- [ ] [Konkretes, testbares Kriterium]
- [ ] Bestehende Tests laufen durch
- [ ] Kein Breaking Change an bestehenden APIs

#### Risiken
- [Was kann schiefgehen — Produktivsystem!]
- [Was muss vorher gesichert/getestet werden]
```

---

## Phase 4: Gesamtübersicht

### Gewichtete Score-Tabelle

```
| Kategorie                    | Gewicht | Aktuell | Nach Umsetzung | Status-Tag      | Alltag     | Sprint |
|------------------------------|---------|---------|----------------|-----------------|------------|--------|
| Natürliche Konversation      | ×3      | XX%     | XX%            | [VERBESSERBAR]  | [TÄGLICH]  | 1,3    |
| Persönlichkeit & Humor       | ×3      | XX%     | XX%            | [OK]            | [TÄGLICH]  | -      |
| Proaktives Handeln           | ×2.5    | XX%     | XX%            | ...             | ...        | ...    |
| Butler-Qualitäten            | ×2.5    | XX%     | XX%            | ...             | ...        | ...    |
| Situationsbewusstsein        | ×2      | XX%     | XX%            | ...             | ...        | ...    |
| Lernfähigkeit                | ×2      | XX%     | XX%            | ...             | ...        | ...    |
| Sprecherkennung              | ×1.5    | XX%     | XX%            | ...             | ...        | ...    |
| Krisenmanagement             | ×1.5    | XX%     | XX%            | ...             | ...        | ...    |
| Sicherheit                   | ×1.5    | XX%     | XX%            | ...             | ...        | ...    |
| Multi-Room-Awareness         | ×1      | XX%     | XX%            | ...             | ...        | ...    |
| Energiemanagement            | ×1      | XX%     | XX%            | ...             | ...        | ...    |
| Erklärbarkeit                | ×1      | XX%     | XX%            | ...             | ...        | ...    |
|------------------------------|---------|---------|----------------|-----------------|------------|--------|
| **GEWICHTETER GESAMT-SCORE** |         | **XX%** | **XX%**        |                 |            |        |
```

Formel: `Gesamt-Score = Σ(Kategorie-% × Gewicht) / Σ(Gewichte)`

### Besser als MCU — Alleinstellungsmerkmale
| Feature | Was es kann | MCU-Äquivalent | Bewertung |
|---------|-------------|----------------|-----------|
| ...     | ...         | ...            | [BESSER ALS MCU] |

**Schutzliste:** Diese Features dürfen durch KEINE Verbesserung beschädigt werden. Jeder Sprint muss gegen diese Liste geprüft werden.

### Fehlende Features (komplett neu zu bauen)
| Feature | MCU-Referenz | Aufwand | Alltag | Sprint |

### Top-10 Quick Wins (Impact/Aufwand-Verhältnis)
Sortiere nach: `(Prozent-Gewinn × Kategorie-Gewicht × Alltags-Faktor) / Aufwand`
- Alltags-Faktor: [TÄGLICH]=3, [WÖCHENTLICH]=2, [SELTEN]=1

### Kritischer Pfad zum MCU-Level
Minimale Menge an Änderungen für ≥90% gewichteten Score. Fokus auf ×3 und ×2.5 Kategorien.

### Fazit
- **Aktueller Stand:** XX% — [Einschätzung in 1 Satz]
- **Erreichbar nach Umsetzung:** XX%
- **Größte Stärke:** [Was der reale Jarvis besser macht als MCU]
- **Größte Schwäche:** [Was am weitesten entfernt UND hohes Gewicht hat]
- **Alltagsrelevanteste Verbesserung:** [Was täglich am meisten betrifft]
- **Empfehlung:** [Womit sofort starten]

---

## Anweisungen für den umsetzenden Agenten

Füge diesen Block in die Plan-Datei ein (falls nicht schon vorhanden):

```
## Anweisungen für den umsetzenden Agenten

Du bist ein Code-Agent der diesen Plan umsetzt. Folge diesen Regeln:
- Arbeite die Sprints in Reihenfolge ab — überspringe keinen Sprint
- Überspringe Aufgaben die als `[x]` oder `⏭️` markiert sind
- Aufgaben mit `[~]` müssen fertiggestellt werden — lies was noch fehlt
- Prüfe nach jeder Aufgabe die Akzeptanzkriterien
- Ändere NIEMALS sicherheitskritische Logik ohne explizite Freigabe
- Führe nach jedem Sprint die Tests aus: `cd assistant && python -m pytest --tb=short -q`
- Committe nach jedem Sprint
- Achte auf die Schutzliste — diese Features dürfen NICHT beschädigt werden
- Verwende den vollständigen Executor-Prompt: `docs/prompts/jarvis-mcu-executor.md`
```

---

## Ergebnis-Datei aktualisieren

Öffne **`docs/prompts/jarvis-mcu-implementation-plan.md`** und:

### Erster Durchlauf (Roadmap noch nicht in der Datei)
1. **Füge die komplette Roadmap hinzu** (Abhängigkeitsgraph, Sprints, Aufgaben, Implementierungsanweisungen)
2. **Erstelle die Gesamtübersicht** mit allen 12 Kategorien
3. **Aktualisiere** den Fortschritts-Tracker
4. **Ergänze** Schutzliste, Quick Wins, Fazit, Anweisungen für den Executor

### Folge-Durchläufe (Roadmap existiert bereits)

Arbeite **inkrementell statt komplett neu**:

1. **Lies die bestehende Plan-Datei** komplett — verstehe den aktuellen Stand
2. **Prüfe per `git diff`** welche Dateien sich seit dem letzten Durchlauf geändert haben:
   ```bash
   git log --oneline -10
   git diff --name-only HEAD~X
   ```
3. **Erledigte Sprint-Aufgaben markieren:**
   - `[ ]` → `[x]` mit `✅ Erledigt am [Datum] — Durchlauf #X`
   - `[ ]` → `[~]` mit Beschreibung was fehlt
   - Akzeptanzkriterien tatsächlich prüfen — nicht blind abhaken!
4. **Neue Aufgaben:** `🆕 Hinzugefügt in Durchlauf #X` — nächste freie Nummer
5. **Obsoletes:** `⏭️ Obsolet — [Grund]`
6. **Zeilenreferenzen:** Aktualisieren wo Code sich geändert hat → `🔄`
7. **Sprint-Status aktualisieren:**
   - `[ ] Offen` → `[~] In Arbeit` → `[x] Abgeschlossen`
   - `Vorher → Nachher: XX% → XX% (Ziel) | Tatsächlich: XX% (nach Durchlauf #X)`
8. **Gesamtübersicht:** Score neu berechnen
9. **Quick Wins:** Erledigte raus, neue rein
10. **Fazit:** Aktuellen Stand neu formulieren
11. **Changelog ergänzen:**
    ```
    ### Durchlauf #X — Session 4 — [Datum]
    - XX Aufgaben als erledigt markiert
    - XX neue Aufgaben hinzugefügt
    - XX Zeilenreferenzen aktualisiert
    - Sprint-Status: [Zusammenfassung]
    - Gewichteter MCU-Score: XX% (vorher: XX%, Δ: +XX%)
    ```

**NIEMALS bestehende Einträge löschen** — nur Status-Updates, Ergänzungen und Markierungen.

---

*Session 4 von 5. Nächste Session: `jarvis-mcu-session-5.md` (Gegenprüfung & Finalisierung)*
