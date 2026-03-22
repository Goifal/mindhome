# Session 3: J.A.R.V.I.S. MCU vs. MindHome — Basis-Kategorien (×1) + Roadmap

> **Verwendung:** Diesen Prompt an Claude Code geben. NUR Session 3 ausführen — danach stoppen.
> **Voraussetzung:** Session 1 + 2 müssen abgeschlossen sein. Die Plan-Datei muss 9 Kategorien enthalten.
> **Ergebnis:** Wird in die bestehende `docs/prompts/jarvis-mcu-implementation-plan.md` ergänzt.

---

## Deine Aufgabe

Du bist ein Elite-Software-Architekt und MCU-Experte. Du kennst J.A.R.V.I.S. aus dem Marvel Cinematic Universe in- und auswendig.

**Dies ist Session 3 von 4.** Du machst zwei Dinge:

### Teil A: Letzte 3 Kategorien analysieren (×1 Gewicht)

| Kategorie | Gewicht | Verifizierung |
|-----------|---------|---------------|
| 10. Multi-Room-Awareness & Follow-Me | **×1** | Nur V1 (solide Einzelverifizierung) |
| 11. Energiemanagement & Haussteuerung | **×1** | Nur V1 |
| 12. Erklärbarkeit & Transparenz | **×1** | Nur V1 |

### Teil B: Roadmap & Sprints erstellen (Phase 2-4)

Nachdem alle 12 Kategorien analysiert sind:
1. **Abhängigkeitsgraph** erstellen
2. **Sprint-Plan** mit konkreten Aufgaben
3. **Implementierungsanweisungen** für jede Aufgabe
4. **Gesamtübersicht** mit gewichtetem Score

### Vorbereitung
1. **Lies zuerst** `docs/prompts/jarvis-mcu-implementation-plan.md` — verstehe was Session 1+2 bereits analysiert haben
2. Analysiere die 3 restlichen Kategorien
3. Erstelle dann die Roadmap basierend auf ALLEN 12 Kategorien

---

## Regeln

### Regel 1: Nur realistische Fähigkeiten
Ignoriere alles aus dem MCU, was physisch unmöglich oder irrelevant für ein Smart Home ist.

### Regel 2: Verifizierung — Nur V1 (Gewicht ×1)
1. **V1 — Solide Verifizierung:** Gründliche Erstanalyse, Dokumentation der Funde.
2. V2 wird nicht durchgeführt. Dokumentiere: `[V2 entfällt — Gewicht ×1]`

### Regel 3: Tiefenanalyse
- Lies die tatsächliche Logik, nicht nur Dateinamen
- Prüfe ob Features tatsächlich verwendet werden
- Suche nach `# TODO`, `# FIXME`, `pass`, `NotImplementedError`

### Regel 4: Prozent-Bewertung
- **0-20%:** Grundidee, kaum funktional
- **21-40%:** Basisfunktionalität, weit vom MCU-Level
- **41-60%:** Solide Grundlage, spürbare Lücken
- **61-80%:** Gute Implementierung, fehlen Feinheiten
- **81-95%:** Nahe MCU-Level, nur Details fehlen
- **96-100%:** Gleichwertig oder besser als MCU

### Regel 5: Alltagsrelevanz-Filter
- `[TÄGLICH]` — bei jeder Interaktion spürbar
- `[WÖCHENTLICH]` — regelmäßig aber nicht ständig
- `[SELTEN]` — nur in speziellen Situationen

### Regel 6: "Besser als MCU" markieren als `[BESSER ALS MCU]`

### Regel 7: Feature-Status
- `[OK]`, `[VERBESSERBAR]`, `[UNTERVERBUNDEN]`, `[VERALTET]`, `[FEHLT KOMPLETT]`, `[STUB/UNFERTIG]`

### Regel 8: Kontext-Limit-Strategie
- Nie ganze Dateien laden — Grep nutzen
- Kategorien sequentiell abarbeiten
- Notizen sofort aufschreiben

---

## MCU-Szenen-Katalog (für Session 3 relevant)

### Iron Man 1 (2008)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "Good morning, Jarvis" | Raum-Kontext, Tagesbriefing | Multi-Room |
| "Reduce heat in the workshop" | Natürliche Steuerung | Energiemanagement |

### Avengers 1 (2012)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| Jarvis scannt Stark Tower Energiesystem | Energieanalyse | Energy Optimizer |

### Avengers 2 (2015)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "Sir, may I remind you..." | Erklärt Empfehlungen | Erklärbarkeit |

### Übergreifende Eigenschaften
| Eigenschaft | Details |
|-------------|---------|
| **Überall präsent** | In jedem Raum verfügbar, folgt Tony |
| **Erklärt sich** | Nennt Gründe für Empfehlungen |
| **Energie-aware** | Kennt Energiestatus des gesamten Hauses |

---

## Teil A: Vergleichskategorien (nur Session 3)

### 10. Multi-Room-Awareness & Follow-Me (Gewicht: ×1)
**MCU-Referenz:** Jarvis ist überall im Haus präsent, folgt Tony von Raum zu Raum, passt Lautstärke und Kontext an.
- Follow-Me Audio?
- Raum-basierte Kontextanpassung?
- Nahtlose Übergänge zwischen Räumen?

### 11. Energiemanagement & Haussteuerung (Gewicht: ×1)
**MCU-Referenz:** Jarvis steuert das gesamte Haus effizient — Licht, Klima, Sicherheit — alles integriert und optimiert.
- Wie intelligent ist die Energieoptimierung?
- Wie viele Gerätetypen werden unterstützt?
- Automatische Optimierungen vs. manuelle Regeln?
- Konflikterkennung (Fenster offen + Heizung)?

### 12. Erklärbarkeit & Transparenz (Gewicht: ×1)
**MCU-Referenz:** "Sir, may I remind you that you've been awake for 72 hours?" — Jarvis erklärt seine Empfehlungen, nennt Gründe.
- XAI / Explainability?
- Begründet Jarvis seine Entscheidungen?
- Nachvollziehbarkeit für den Benutzer?

---

## Ausgabeformat für Kategorien

```
## [Kategorie-Name]

### MCU-Jarvis Benchmark
[Szenen-Referenzen]

### MindHome-Jarvis Status: XX%

### Code-Verifizierung
**[V1] Analyse:**
- Datei: `pfad/zur/datei.py` — Funktion `xyz()` (Zeile XX-YY)
- [Was die Implementierung tut]

**[V2 entfällt — Gewicht ×1]**

### Was fehlt zum MCU-Level
1. [Punkt] — [Begründung]

### Konkrete Verbesserungsvorschläge
1. **[Titel]** — Aufwand: X, Impact: X%, Alltag: [TAG]

### Akzeptanzkriterien
- [ ] Kriterium 1
```

---

## Teil B: Roadmap erstellen (Phase 2-4)

Nachdem die letzten 3 Kategorien analysiert sind, erstelle die Roadmap.

### Phase 2: Abhängigkeitsgraph & Sprint-Plan

#### Abhängigkeitsgraph
Welche Verbesserungen müssen VOR anderen umgesetzt werden?
```
[Feature A] ──→ [Feature B] ──→ [Feature C]
                                 ↗
[Feature D] ────────────────────┘
```

#### Sprint-Plan
Teile alle Verbesserungen in Sprints auf. Sortiere nach:
1. **Abhängigkeiten zuerst**
2. **Höchster Impact zuerst** (Gewicht × Prozent-Gewinn)
3. **Quick Wins vorziehen**
4. **Risiko minimieren**
5. **Vernetzung maximieren**

Format pro Sprint:
```
### Sprint X: [Thema]
**Ziel:** [Was MCU-Level sein soll]
**Vorher → Nachher:** XX% → XX%

1. [Aufgabe] — Datei: `pfad`, Funktion: `xyz()`
   - Was zu tun ist
   - Akzeptanzkriterium

**Validierung:**
- [ ] Tests grün
- [ ] Kein Breaking Change
- [ ] Schutzliste geprüft
```

### Phase 3: Implementierungsanweisungen

Für **jede Aufgabe** in den Sprints:

```
### Aufgabe X.Y: [Titel]
**Sprint:** X | **Priorität:** [Kritisch/Hoch/Mittel] | **Aufwand:** [Klein/Mittel/Groß]

#### Ist-Zustand
- Datei: `pfad/zur/datei.py`
- Aktuelle Implementierung: [Was der Code jetzt tut, mit Zeilenreferenz]
- Problem: [Was fehlt]

#### Soll-Zustand (MCU-Level)
- [Genau wie es nachher funktionieren soll]

#### Implementierungsschritte
1. In `datei.py`, Funktion `xyz()`: [Was ändern]
2. Neue Methode `abc()`: [Logik]
3. In `brain.py` einbinden: [Wo/Wie]
4. In `settings.yaml`: [Config-Optionen]

#### Akzeptanzkriterien
- [ ] [Testbar]
- [ ] Kein Regressions-Bruch
- [ ] Konfigurierbar in settings.yaml

#### Risiken
- [Was könnte schiefgehen — Produktivsystem!]
```

**WICHTIG:** Anweisungen müssen so konkret sein, dass ein Code-Agent sie **ohne Rückfragen** umsetzen kann.

### Phase 4: Gesamtübersicht

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

#### Besser als MCU — Alleinstellungsmerkmale
| Feature | Was es kann | MCU-Äquivalent | Bewertung |
|---------|-------------|----------------|-----------|
| ...     | ...         | ...            | [BESSER ALS MCU] |

**Schutzliste:** Diese Features dürfen durch KEINE Verbesserung beschädigt werden.

#### Fehlende Features (komplett neu zu bauen)
| Feature | MCU-Referenz | Aufwand | Alltag | Sprint |

#### Top-10 Quick Wins
Sortiere nach: `(Prozent-Gewinn × Kategorie-Gewicht × Alltags-Faktor) / Aufwand`
- Alltags-Faktor: [TÄGLICH]=3, [WÖCHENTLICH]=2, [SELTEN]=1

#### Kritischer Pfad zum MCU-Level
Minimale Menge an Änderungen für ≥90% gewichteten Score. Fokus auf ×3 und ×2.5 Kategorien.

#### Fazit
- **Aktueller Stand:** XX% — [Einschätzung]
- **Erreichbar nach Umsetzung:** XX%
- **Größte Stärke:** [Besser als MCU]
- **Größte Schwäche:** [Am weitesten entfernt UND hohes Gewicht]
- **Alltagsrelevanteste Verbesserung:** [Was täglich am meisten betrifft]
- **Empfehlung:** [Womit sofort starten]

---

## Ergebnis-Datei aktualisieren

Öffne **`docs/prompts/jarvis-mcu-implementation-plan.md`** und:

### Erster Durchlauf (Kategorien 10-12 + Roadmap noch nicht in der Datei)
1. **Ergänze** die 3 neuen Kategorien nach den bestehenden 9
2. **Füge die komplette Roadmap hinzu** (Sprints, Aufgaben, Implementierungsanweisungen)
3. **Erstelle die Gesamtübersicht** mit allen 12 Kategorien
4. **Aktualisiere** den Fortschritts-Tracker (12 von 12 Kategorien + Roadmap)
5. **Berechne** den gewichteten Gesamt-Score
6. **Ergänze** Schutzliste, Quick Wins, Fazit

### Folge-Durchläufe (Roadmap existiert bereits)

Arbeite **inkrementell statt komplett neu**:

1. **Lies die bestehende Plan-Datei** komplett — verstehe den aktuellen Stand
2. **Prüfe per `git diff`** welche Dateien sich seit dem letzten Durchlauf geändert haben:
   ```bash
   git log --oneline -10
   git diff --name-only HEAD~X
   ```
3. **Kategorien 10-12:** Neuanalyse bei Code-Änderungen, Stichprobe wenn unverändert
4. **Roadmap aktualisieren:**
   - Erledigte Sprint-Aufgaben: `[ ]` → `[x]` mit `✅ Erledigt am [Datum] — Durchlauf #X`
   - Teilweise erledigte: `[ ]` → `[~]` mit Beschreibung was fehlt
   - Prüfe ob Akzeptanzkriterien **tatsächlich** erfüllt sind
   - Neue Aufgaben: `🆕 Hinzugefügt in Durchlauf #X` — nächste freie Nummer
   - Obsolete Aufgaben: `⏭️ Obsolet — [Grund]`
   - Zeilenreferenzen aktualisieren: `🔄`
5. **Sprint-Status aktualisieren:**
   - `[ ] Offen` → `[~] In Arbeit` → `[x] Abgeschlossen`
   - `Vorher → Nachher: XX% → XX% (Ziel) | Tatsächlich: XX% (nach Durchlauf #X)`
6. **Gesamtübersicht:** Score neu berechnen basierend auf aktuellem Code
7. **Quick Wins:** Neu sortieren — erledigte raus, neue rein
8. **Fazit:** Aktuellen Stand neu formulieren
9. **Changelog ergänzen:**
   ```
   ### Durchlauf #X — Session 3 — [Datum]
   - XX Aufgaben als erledigt markiert
   - XX neue Aufgaben hinzugefügt
   - XX Zeilenreferenzen aktualisiert
   - Sprint-Status: [Zusammenfassung]
   - Gewichteter MCU-Score: XX% (vorher: XX%, Δ: +XX%)
   ```

**NIEMALS bestehende Einträge löschen** — nur Status-Updates, Ergänzungen und Markierungen.

### Anweisungen für den umsetzenden Agenten

Füge diesen Block am Anfang der Plan-Datei ein (falls nicht schon vorhanden):

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
```

---

*Session 3 von 4. Nächste Session: `jarvis-mcu-session-4.md` (Gegenprüfung & Finalisierung)*
