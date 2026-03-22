# Session 3: J.A.R.V.I.S. MCU vs. MindHome — Basis-Kategorien (×1)

> **Verwendung:** Diesen Prompt an Claude Code geben. NUR Session 3 ausführen — danach stoppen.
> **Scope:** NUR den Assistenten analysieren (`assistant/` Verzeichnis). Das Add-on (`addon/`) ist NICHT Teil dieser Analyse.
> **Voraussetzung:** Session 1 + 2 müssen abgeschlossen sein. Die Plan-Datei muss 9 Kategorien enthalten.
> **Ergebnis:** Wird in die bestehende `docs/prompts/jarvis-mcu-implementation-plan.md` ergänzt.

---

## Deine Aufgabe

Du bist ein Elite-Software-Architekt und MCU-Experte. Du kennst J.A.R.V.I.S. aus dem Marvel Cinematic Universe in- und auswendig.

**Dies ist Session 3 von 5.** Du analysierst die letzten 3 Kategorien mit niedrigster Gewichtung:

| Kategorie | Gewicht | Verifizierung |
|-----------|---------|---------------|
| 10. Multi-Room-Awareness & Follow-Me | **×1** | Nur V1 (solide Einzelverifizierung) |
| 11. Energiemanagement & Haussteuerung | **×1** | Nur V1 |
| 12. Erklärbarkeit & Transparenz | **×1** | Nur V1 |

**Nach Abschluss:** Schreibe die Ergebnisse in die Plan-Datei. Die Roadmap wird in Session 4 erstellt.

### Durchlauf-Nummer ermitteln
Lies den **Changelog** am Ende von `docs/prompts/jarvis-mcu-implementation-plan.md`. Zähle die bestehenden Durchlauf-Einträge. Dein Durchlauf ist **der nächste** (z.B. wenn der letzte `#2` war, bist du `#3`). Beim allerersten Durchlauf (kein Changelog vorhanden) bist du `#1`.

### Vorbereitung
1. **Lies zuerst** `docs/prompts/jarvis-mcu-implementation-plan.md` — verstehe was Session 1+2 bereits analysiert haben
2. Analysiere die 3 restlichen Kategorien

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

### Regel 9: Inkrementelles Schreiben — NIEMALS alles auf einmal
> **KRITISCH:** Claude Code friert ein oder trunkiert bei großen Write-Aufrufen (>400 Zeilen).
> Die Plan-Datei MUSS in kleinen Abschnitten geschrieben werden.

**Schreibstrategie:**
1. **Pro Kategorie:** Nach jeder fertigen Kategorie sofort per **Edit-Tool** an die Plan-Datei anhängen (~80-150 Zeilen)
2. **Niemals die gesamte Datei neu schreiben** — immer nur den neuen Abschnitt per Edit einfügen
3. **Changelog:** Am Ende separat per Edit anhängen
4. **Technisch:** Verwende das Edit-Tool mit einem Anker-String (z.B. dem letzten Abschnitt) um den neuen Abschnitt direkt darunter einzufügen

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

## Vergleichskategorien (nur Session 3)

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

## Ergebnis-Datei aktualisieren

Öffne **`docs/prompts/jarvis-mcu-implementation-plan.md`** und:

### Erster Durchlauf (Kategorien 10-12 noch nicht in der Datei)
1. **Ergänze** die 3 neuen Kategorien-Analysen nach den bestehenden 9
2. **Aktualisiere** den Fortschritts-Tracker (12 von 12 Kategorien analysiert)
3. **Ergänze** die Schutzliste falls neue "Besser als MCU" Features gefunden wurden
4. **Berechne** den Teilergebnis-Score (jetzt mit allen 12 Kategorien)

### Folge-Durchläufe (Kategorien 10-12 existieren bereits)

Arbeite **inkrementell statt komplett neu**:

1. **Lies die bestehende Plan-Datei** und identifiziere den aktuellen Stand der Kategorien 10-12
2. **Prüfe per `git diff`** welche Dateien sich seit dem letzten Durchlauf geändert haben:
   ```bash
   git log --oneline -10
   git diff --name-only HEAD~X
   ```
3. **Kategorien mit Code-Änderungen:** Volle Neuanalyse (V1)
4. **Kategorien ohne Code-Änderungen:** Stichproben-Prüfung, Status beibehalten wenn nichts auffällt
5. **Erledigtes markieren:** Prüfe jede Aufgabe gegen den aktuellen Code:
   - `[ ]` → `[x]` wenn umgesetzt: `✅ Erledigt am [Datum] — Durchlauf #X`
   - `[ ]` → `[~]` wenn teilweise: `[~] Teilweise erledigt — [Was noch fehlt]`
   - Prüfe ob Akzeptanzkriterien **tatsächlich** erfüllt sind (nicht blind abhaken!)
6. **Neue Erkenntnisse:** Markiere mit `🆕 Hinzugefügt in Durchlauf #X`
7. **Veraltetes anpassen:**
   - Zeilenreferenzen aktualisieren → `🔄`
   - Obsolete Aufgaben → `⏭️ Obsolet — [Grund]`
8. **Prozent-Bewertung** der Kategorien 10-12 neu berechnen
9. **Changelog am Ende der Datei ergänzen:**
   ```
   ### Durchlauf #X — Session 3 — [Datum]
   - XX Aufgaben als erledigt markiert
   - XX neue Aufgaben hinzugefügt
   - XX Zeilenreferenzen aktualisiert
   - Kategorien 10-12 Score: [vorher → nachher]
   ```

**NIEMALS bestehende Einträge löschen** — nur Status-Updates, Ergänzungen und Markierungen.

---

*Session 3 von 5. Nächste Session: `jarvis-mcu-session-4.md` (Roadmap & Sprints)*
