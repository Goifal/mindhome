# Session 5: J.A.R.V.I.S. MCU vs. MindHome — Gegenprüfung & Finalisierung

> **Verwendung:** Diesen Prompt an Claude Code geben. NUR Session 5 ausführen.
> **Scope:** NUR den Assistenten (`assistant/` Verzeichnis). Gegenprüfung bezieht sich ausschließlich auf den Assistenten-Code.
> **Voraussetzung:** Session 1-4 müssen abgeschlossen sein. Die Plan-Datei muss alle 12 Kategorien + Roadmap enthalten.
> **Ergebnis:** Verifizierte und finalisierte `docs/prompts/jarvis-mcu-implementation-plan.md`
> **Empfehlung:** Diese Session idealerweise in einer **separaten Konversation** ausführen für frischen Kontext.

---

## Deine Aufgabe

Du bist ein Elite-Software-Architekt. Die vorherigen 4 Sessions haben eine vollständige MCU-Analyse mit Implementierungs-Roadmap erstellt. **Dein Job ist die Qualitätssicherung.**

**Dies ist Session 5 von 5.** Du prüfst die bestehende Plan-Datei gegen den **aktuellen Code** und stellst sicher, dass:
1. Alle Erkenntnisse korrekt sind
2. Alle Code-Referenzen stimmen
3. Keine Features übersehen wurden
4. Die Sprint-Reihenfolge sinnvoll ist
5. Kein Verbesserungsvorschlag bestehende Features beschädigt

**Wichtig:** Du hast frischen Kontext — nutze das! Die vorherigen Sessions hatten am Ende möglicherweise Kontext-Limit-Probleme. Du prüfst jetzt alles mit voller Aufmerksamkeit.

### Inkrementelles Schreiben — NIEMALS alles auf einmal
> **KRITISCH:** Claude Code friert ein oder trunkiert bei großen Write-Aufrufen (>400 Zeilen).
> Änderungen an der Plan-Datei MÜSSEN in kleinen Abschnitten per **Edit-Tool** gemacht werden.
> **Niemals die gesamte Datei neu schreiben** — immer nur gezielte Edits (Korrekturen, Ergänzungen, Status-Updates).

### Durchlauf-Nummer ermitteln
Lies den **Changelog** am Ende von `docs/prompts/jarvis-mcu-implementation-plan.md`. Zähle die bestehenden Durchlauf-Einträge. Dein Durchlauf ist **der nächste** (z.B. wenn der letzte `#3` war, bist du `#4`). Beim allerersten Durchlauf (kein Changelog vorhanden) bist du `#1`.

---

## Vorbereitung

1. **Lies die komplette Plan-Datei** `docs/prompts/jarvis-mcu-implementation-plan.md`
2. **Lies diesen Prompt** für die Prüfkriterien
3. Arbeite die Gegenprüfung systematisch durch

---

## Schritt 1: Erkenntnisse gegen den Code prüfen

Gehe die Plan-Datei **Kategorie für Kategorie** durch:

### Für jeden "fehlt"-Punkt (`[FEHLT KOMPLETT]`):
- Suche mit **3+ verschiedenen Suchbegriffen** (Synonyme, alternative Funktionsnamen, andere Dateien)
- Erst wenn ALLE Suchversuche leer sind: bestätige `[FEHLT KOMPLETT]`
- Wenn du doch etwas findest: markiere als `[KORRIGIERT]` und beschreibe was gefunden wurde

### Für jeden Verbesserungsvorschlag:
- Prüfe ob die referenzierte **Datei existiert**
- Prüfe ob die referenzierte **Funktion existiert**
- Prüfe ob **Zeilenangaben** noch stimmen (Code kann sich geändert haben)
- Wenn veraltet: aktualisiere die Referenz und markiere mit `🔄`

### Für jede Prozent-Bewertung:
- Lies die relevanten Code-Stellen **nochmal**
- Frage: "Bin ich fair? Habe ich etwas übersehen?"
- Wenn die Bewertung angepasst werden muss: markiere mit `[KORRIGIERT]` und begründe

### Für jeden Sprint-Task:
- Prüfe ob die vorgeschlagene Änderung **keine bestehende Funktionalität bricht**
- Schau nach **Abhängigkeiten** — wer ruft die zu ändernde Funktion auf?
- Gibt es **Tests** die brechen könnten?
- Prüfe gegen die **Schutzliste** — wird ein "Besser als MCU" Feature beschädigt?

---

## Schritt 2: Vollständigkeitsprüfung

### Fehlende Features suchen
Suche aktiv nach MCU-Fähigkeiten die in **keiner der 12 Kategorien** behandelt wurden:
- Gibt es Features die zwischen den Kategorien fallen?
- Hat Session 1/2/3 etwas übersehen?
- Neue Kategorien erstellen wenn nötig

### Feature-Vernetzung prüfen
MCU-Jarvis hat alles nahtlos integriert. Prüfe für jedes Feature:
- Arbeitet es mit anderen Modulen zusammen?
- Gibt es isolierte Features die vernetzt sein sollten?
- Markiere `[UNTERVERBUNDEN]` wenn Features isoliert arbeiten

### Konfiguration prüfen
- Sind alle Features in `settings.yaml` **aktiviert**?
- Sind Schwellwerte **sinnvoll** oder willkürlich?
- Gibt es Features die konfigurierbar sein sollten aber es nicht sind?

---

## Schritt 3: Sprint-Plan validieren

### Abhängigkeiten
- Stimmt die Sprint-Reihenfolge? Werden Abhängigkeiten respektiert?
- Gibt es versteckte Abhängigkeiten die nicht im Graph sind?

### Risiko-Assessment
- Welche Aufgaben sind **besonders riskant** für das Produktivsystem?
- Haben diese Aufgaben angemessene Vorsichtsmaßnahmen?
- Sind Rollback-Strategien beschrieben?

### Aufwand-Schätzungen
- Sind "Klein/Mittel/Groß" realistisch?
- Gibt es Aufgaben die als "Klein" markiert sind aber eigentlich komplex?

---

## Schritt 4: Plan-Datei finalisieren

Aktualisiere `docs/prompts/jarvis-mcu-implementation-plan.md`:

### Korrekturen einarbeiten
- Alle `[KORRIGIERT]`-Markierungen mit Erklärung
- Alle `🔄`-Markierungen für aktualisierte Referenzen
- Neue Features/Kategorien die entdeckt wurden als `🆕`

### Erledigtes markieren (bei Folge-Durchläufen)
- `[ ]` → `[x]` mit `✅ Erledigt am [Datum] — Durchlauf #X`
- `[ ]` → `[~]` mit Beschreibung was fehlt
- Akzeptanzkriterien tatsächlich prüfen — nicht blind abhaken!

### Fortschritts-Tracker aktualisieren
```
| Session | Datum | Kategorien | Aufgaben |
|---------|-------|------------|----------|
| 1       | [Datum] | 1-4 (×3/×2.5) | XX |
| 2       | [Datum] | 5-9 (×2/×1.5) | XX |
| 3       | [Datum] | 10-12 (×1) | XX |
| 4       | [Datum] | Roadmap & Sprints | XX |
| 5       | [Datum] | Gegenprüfung | XX Korrekturen |
```

### Gesamt-Score neu berechnen
Berechne den gewichteten Score basierend auf den (möglicherweise korrigierten) Prozent-Bewertungen:

`Gesamt-Score = Σ(Kategorie-% × Gewicht) / Σ(Gewichte)`

| Kategorie | Gewicht |
|-----------|---------|
| Natürliche Konversation | ×3 |
| Persönlichkeit & Humor | ×3 |
| Proaktives Handeln | ×2.5 |
| Butler-Qualitäten | ×2.5 |
| Situationsbewusstsein | ×2 |
| Lernfähigkeit | ×2 |
| Sprecherkennung | ×1.5 |
| Krisenmanagement | ×1.5 |
| Sicherheit | ×1.5 |
| Multi-Room | ×1 |
| Energiemanagement | ×1 |
| Erklärbarkeit | ×1 |

### Changelog ergänzen
```
### Durchlauf #X — Session 5 (Gegenprüfung) — [Datum]
- XX Erkenntnisse als [KORRIGIERT] markiert
- XX Zeilenreferenzen aktualisiert (🔄)
- XX neue Erkenntnisse hinzugefügt (🆕)
- XX Aufgaben als erledigt markiert
- Gewichteter MCU-Score: XX% (vorher: XX%, Δ: ±XX%)
- Korrekturen: [Zusammenfassung der wichtigsten Änderungen]
```

**NIEMALS bestehende Einträge löschen** — nur Status-Updates, Ergänzungen und Markierungen.

---

## Qualitätskriterien — Die Plan-Datei ist NUR akzeptabel wenn:

- [ ] Jede Aufgabe einen **konkreten Dateipfad** hat (kein "in der relevanten Datei")
- [ ] Jede Aufgabe **konkrete Zeilenreferenzen** hat (verifiziert gegen aktuellen Code)
- [ ] Jede Aufgabe **Akzeptanzkriterien** hat die testbar sind
- [ ] Die Sprint-Reihenfolge **Abhängigkeiten** respektiert
- [ ] Ein Agent der NUR die Plan-Datei liest, **jeden Punkt umsetzen kann**
- [ ] **Keine vagen Formulierungen** ("verbessere", "optimiere") — nur konkrete Anweisungen
- [ ] Alle Erkenntnisse durch die **Gegenprüfung bestätigt** wurden
- [ ] Die **Schutzliste** vollständig ist und kein Sprint sie verletzt
- [ ] Der **Gesamt-Score korrekt berechnet** ist

Wenn eines dieser Kriterien NICHT erfüllt ist: behebe es bevor du fertig bist.

---

## Folge-Durchläufe

Bei wiederholten Durchläufen von Session 5:

1. **Fokussiere auf Code-Änderungen** seit der letzten Gegenprüfung (`git diff`)
2. **Prüfe ob Korrekturen aus dem letzten Durchlauf** tatsächlich eingearbeitet wurden
3. **Stichproben** in unveränderten Bereichen
4. **Neue Sprint-Aufgaben** validieren die in Session 4 hinzugefügt wurden

---

## Abschluss

Nach der Finalisierung:
1. Prüfe die Plan-Datei ein letztes Mal auf Konsistenz
2. Stelle sicher dass alle Abschnitte vorhanden sind
3. Der nächste Schritt ist: Plan-Datei mit dem Executor-Agent umsetzen
   → Verwende dafür `docs/prompts/jarvis-mcu-executor.md`

---

*Session 5 von 5. Die Analyse ist abgeschlossen. Die Plan-Datei ist bereit zur Umsetzung.*
