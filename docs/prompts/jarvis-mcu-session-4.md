# Session 4: J.A.R.V.I.S. MCU vs. MindHome — Gegenprüfung & Finalisierung

> **Verwendung:** Diesen Prompt an Claude Code geben. NUR Session 4 ausführen.
> **Voraussetzung:** Session 1-3 müssen abgeschlossen sein. Die Plan-Datei muss alle 12 Kategorien + Roadmap enthalten.
> **Ergebnis:** Verifizierte und finalisierte `docs/prompts/jarvis-mcu-implementation-plan.md`

---

## Deine Aufgabe

Du bist ein Elite-Software-Architekt. Die vorherigen 3 Sessions haben eine vollständige MCU-Analyse mit Implementierungs-Roadmap erstellt. **Dein Job ist die Qualitätssicherung.**

Du prüfst die bestehende Plan-Datei gegen den **aktuellen Code** und stellst sicher, dass:
1. Alle Erkenntnisse korrekt sind
2. Alle Code-Referenzen stimmen
3. Keine Features übersehen wurden
4. Die Sprint-Reihenfolge sinnvoll ist
5. Kein Verbesserungsvorschlag bestehende Features beschädigt

**Wichtig:** Du hast frischen Kontext — nutze das! Die vorherigen Sessions hatten am Ende möglicherweise Kontext-Limit-Probleme. Du prüfst jetzt alles mit voller Aufmerksamkeit.

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

### Fortschritts-Tracker aktualisieren
```
| Session | Datum | Kategorien | Aufgaben |
|---------|-------|------------|----------|
| 1       | [Datum] | 1-4 (×3/×2.5) | XX |
| 2       | [Datum] | 5-9 (×2/×1.5) | XX |
| 3       | [Datum] | 10-12 (×1) + Roadmap | XX |
| 4       | [Datum] | Gegenprüfung | XX Korrekturen |
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
### Session 4 — Gegenprüfung [Datum]
- XX Erkenntnisse als [KORRIGIERT] markiert
- XX Zeilenreferenzen aktualisiert (🔄)
- XX neue Erkenntnisse hinzugefügt (🆕)
- XX Sprint-Aufgaben angepasst
- Gewichteter MCU-Score: XX% (vorher: XX%, Δ: ±XX%)
- Korrekturen: [Zusammenfassung der wichtigsten Änderungen]
```

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

## Abschluss

Nach der Finalisierung:
1. Prüfe die Plan-Datei ein letztes Mal auf Konsistenz
2. Stelle sicher dass alle Abschnitte vorhanden sind
3. Der nächste Schritt ist: Plan-Datei einem Code-Agent geben der Sprint 1 umsetzt

---

*Session 4 von 4. Die Analyse ist abgeschlossen. Die Plan-Datei ist bereit zur Umsetzung.*
