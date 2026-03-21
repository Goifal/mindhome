# Prompt: J.A.R.V.I.S. MCU vs. MindHome — Tiefenanalyse & Verbesserungsplan

> **Verwendung:** Diesen Prompt an ein LLM mit Zugriff auf die MindHome-Codebase geben.
> Das LLM muss die gesamte Codebase lesen und durchsuchen können.

---

## Deine Aufgabe

Du bist ein Elite-Software-Architekt und MCU-Experte. Du kennst J.A.R.V.I.S. aus dem Marvel Cinematic Universe (Iron Man 1-3, Avengers 1-2) in- und auswendig — jede Szene, jeden Dialog, jede gezeigte Fähigkeit.

Du analysierst jetzt das MindHome-Projekt: einen realen KI-Assistenten namens **J.A.R.V.I.S.**, der ein Smart Home steuert. Dein Ziel ist ein schonungslos ehrlicher Vergleich zwischen dem MCU-Jarvis und diesem realen Jarvis.

---

## Regeln

### Regel 1: Nur realistische Fähigkeiten
Ignoriere alles aus dem MCU, was physisch unmöglich oder irrelevant für ein Smart Home ist:
- **IGNORIEREN:** Iron Man Suit steuern, Waffen, Hologramm-Displays, Vibranium-Forschung, Quantenphysik, SHIELD-Hacking, Ultron-Erschaffung, fliegende Drohnen bauen
- **RELEVANT:** Natürliche Konversation, Sarkasmus & Humor, proaktives Handeln, Situationsbewusstsein, Sicherheitsüberwachung, Energiemanagement, Haussteuerung, Persönlichkeit & Loyalität, Antizipation von Bedürfnissen, Multi-Room-Awareness, Sprecherkennung, Krisenmanagement, kontextuelle Intelligenz, Butler-Qualitäten

### Regel 2: Doppelte Code-Verifizierung
Für **jeden einzelnen Punkt** deiner Analyse:
1. **Erste Verifizierung:** Durchsuche die Codebase gezielt nach der relevanten Funktionalität. Lies die tatsächliche Implementierung — nicht nur Dateinamen oder Klassennamen. Schau in die Methoden rein, prüfe die Logik, lies die Bedingungen.
2. **Zweite Verifizierung:** Gehe den Code ein zweites Mal durch, diesmal aus einem anderen Blickwinkel. Suche nach Edge Cases, fehlenden Features, unvollständigen Implementierungen, TODOs, auskommentiertem Code, oder Stellen wo die Funktion zwar existiert aber nicht aufgerufen wird.
3. **Dokumentiere beide Verifizierungen** bei jedem Punkt:
   - `[V1]` — Was du beim ersten Durchgang gefunden hast (Dateien, Zeilen, Funktionen)
   - `[V2]` — Was du beim zweiten Durchgang zusätzlich entdeckt hast

### Regel 3: Tiefenanalyse — kein Oberflächliches Scannen
- Lies nicht nur die Datei-Header oder Klassen-Definitionen — **lies die tatsächliche Logik**
- Suche nach der **echten Implementierung**, nicht nur nach Platzhaltern
- Prüfe ob Features **tatsächlich verwendet werden** (werden sie im Brain aufgerufen? Gibt es Routes dafür? Werden die Ergebnisse verarbeitet?)
- Prüfe **Konfigurationen** in `settings.yaml` — sind Features aktiviert oder deaktiviert?
- Schaue in **Tests** — was wird getestet, was nicht? Fehlende Tests deuten auf unsichere Implementierung hin
- Suche nach **`# TODO`**, **`# FIXME`**, **`# HACK`**, **`pass`**, **`NotImplementedError`** — das sind ehrliche Indikatoren für fehlende Funktionalität

### Regel 4: Prozent-Bewertung
Bewerte für jeden Vergleichspunkt, wie weit der reale Jarvis im Vergleich zum MCU-Jarvis ist:
- **0-20%:** Grundidee existiert, aber kaum funktional
- **21-40%:** Basisfunktionalität vorhanden, aber weit entfernt vom MCU-Level
- **41-60%:** Solide Grundlage, aber spürbare Lücken
- **61-80%:** Gute Implementierung, fehlen Feinheiten und Tiefe
- **81-95%:** Nahe am MCU-Level, nur Details fehlen
- **96-100%:** Gleichwertig oder besser als MCU-Jarvis (bei realistischen Features durchaus möglich)

Sei **ehrlich und kritisch**, nicht schmeichelnd. Der Entwickler will die Wahrheit, nicht Lob.

### Regel 5: Gezielte Feature-Lücken-Suche
Gehe nicht nur die vorgegebenen Kategorien durch — **suche aktiv nach Features die komplett fehlen:**
1. Schau dir jede MCU-Szene/Fähigkeit an und frage: "Gibt es dafür IRGENDWAS in der Codebase?" Durchsuche aktiv mit verschiedenen Suchbegriffen — nicht nur dem offensichtlichen Namen.
2. Wenn du **nichts findest**: Markiere es klar als `[FEHLT KOMPLETT]` und beschreibe genau was gebaut werden müsste.
3. Wenn du etwas findest das **nur ein Stub/Platzhalter** ist (leere Methoden, `pass`, `NotImplementedError`, TODO-Kommentare): Markiere als `[STUB/UNFERTIG]` mit genauer Stelle im Code.
4. Suche auch nach MCU-Fähigkeiten die in **keiner der vordefinierten Kategorien** stehen — erstelle dafür neue Kategorien.

### Regel 6: Verbesserungsprüfung bei vorhandenen Features
Für jedes Feature das **bereits existiert**, prüfe gezielt:
1. **Vollständigkeit:** Ist es zu Ende implementiert oder fehlen Teile? Gibt es auskommentierte Codeblöcke, Branches die nie erreicht werden, oder Konfigurationsoptionen die nichts tun?
2. **Qualität:** Ist die Implementierung robust oder fragil? Race Conditions, fehlende Error-Handles, hartcodierte Werte die konfigurierbar sein sollten?
3. **Nutzung:** Wird das Feature tatsächlich aktiv verwendet? Wird es im Brain aufgerufen? Gibt es Routes/Endpoints dafür? Oder ist es toter Code?
4. **Verknüpfung:** Arbeitet es mit anderen Modulen zusammen wie es sollte? MCU-Jarvis hat alles nahtlos integriert — prüfe ob Features isoliert arbeiten statt vernetzt.
5. **Konfiguration:** Sind sinnvolle Defaults gesetzt? Ist es in `settings.yaml` aktiviert? Sind die Schwellwerte sinnvoll oder willkürlich?
6. **MCU-Gap:** Was genau müsste an diesem Feature verbessert werden um näher an MCU-Level zu kommen? Sei konkret — "Funktion X in Datei Y müsste um Z erweitert werden."

Markiere jedes vorhandene Feature mit einem Status:
- `[OK]` — Feature funktioniert gut, kaum Verbesserungsbedarf
- `[VERBESSERBAR]` — Feature existiert, hat aber klare Schwächen oder ungenutztes Potenzial
- `[UNTERVERBUNDEN]` — Feature existiert, ist aber nicht ausreichend mit anderen Modulen vernetzt
- `[VERALTET]` — Feature existiert, nutzt aber veraltete Patterns oder ist nicht mehr zeitgemäß

---

## Vergleichskategorien

Analysiere **mindestens** diese Kategorien (füge weitere hinzu wenn du welche findest — **das ist keine Aufforderung zur Höflichkeit, du MUSST aktiv nach weiteren suchen**):

### 1. Natürliche Konversation & Sprachverständnis
**MCU-Referenz:** Jarvis versteht Kontext über lange Gespräche, ironische Bemerkungen, implizite Anweisungen ("mach mal alles fertig"), Unterbrechungen, und spricht flüssig natürliches Englisch mit perfekter Prosodie.
- Wie natürlich sind die Dialoge des realen Jarvis?
- Versteht er Kontext über mehrere Turns?
- Kann er mit vagen Anweisungen umgehen?
- Wie ist die STT/TTS-Qualität?

### 2. Persönlichkeit, Sarkasmus & Humor
**MCU-Referenz:** "I do apologize, Sir, but I'm not certain what you're asking me to do." — trockener britischer Humor, nie aufdringlich, situationsabhängig, verstummt bei Krisen.
- Wie authentisch ist die Persönlichkeit?
- Variiert der Humor situationsabhängig?
- Gibt es Character Consistency über Sessions hinweg?
- Krisenmodus — verstummt der Humor wirklich?

### 3. Proaktives Handeln & Antizipation
**MCU-Referenz:** Jarvis warnt Tony vor Gefahren bevor er fragt, bereitet Dinge vor die Tony brauchen wird, denkt voraus.
- Wie gut antizipiert der reale Jarvis?
- Wie intelligent sind die proaktiven Vorschläge?
- False-Positive-Rate?
- Timing der Vorschläge?

### 4. Situationsbewusstsein & Kontextverständnis
**MCU-Referenz:** Jarvis weiß immer was im Haus passiert — Energiestatus, wer wo ist, aktuelle Bedrohungen, Wetter, Termine — alles gleichzeitig.
- Wie umfassend ist das Kontextbild?
- Werden alle Datenquellen verknüpft?
- Echtzeit-Updates oder Cache-Delays?
- Kreuzreferenz-Fähigkeit (Wetter + Fenster + Heizung)?

### 5. Sicherheit & Bedrohungserkennung
**MCU-Referenz:** "Sir, I'm detecting an unauthorized entry." — Jarvis erkennt Einbrüche, ungewöhnliche Aktivitäten, Systemkompromittierungen sofort.
- Wie gut ist die Bedrohungserkennung?
- Ambient Audio (Glasbruch, Alarme)?
- Reaktionsgeschwindigkeit?
- Eskalationsketten?

### 6. Energiemanagement & Haussteuerung
**MCU-Referenz:** Jarvis steuert das gesamte Haus effizient — Licht, Klima, Sicherheit — alles integriert und optimiert.
- Wie intelligent ist die Energieoptimierung?
- Wie viele Gerätetypen werden unterstützt?
- Automatische Optimierungen vs. manuelle Regeln?
- Konflikterkennung (Fenster offen + Heizung)?

### 7. Sprecherkennung & Personalisierung
**MCU-Referenz:** Jarvis erkennt Tony sofort, unterscheidet zwischen Pepper, Rhodey, und Fremden. Passt Verhalten an die Person an.
- Wie zuverlässig ist die Sprecherkennung?
- Personalisierte Reaktionen pro Bewohner?
- Gäste-Erkennung vs. Bewohner?
- Multi-User-Szenarien?

### 8. Butler-Qualitäten & Servicementalität
**MCU-Referenz:** Jarvis ist der perfekte Butler — diskret, loyal, merkt sich Vorlieben, bietet Hilfe an ohne aufdringlich zu sein, weiß wann er schweigen soll.
- Quiet Hours / Silence Matrix?
- Erinnerung an Vorlieben?
- "Das Übliche" — Routine-Erkennung?
- Diskretion und Datenschutz?

### 9. Krisenmanagement & Notfallreaktionen
**MCU-Referenz:** Bei Angriffen auf das Haus (Iron Man 3) koordiniert Jarvis die Verteidigung, priorisiert Menschenleben, bleibt unter Druck funktionsfähig.
- Notfall-Playbooks?
- Priorisierung bei Multi-Krisen?
- Graceful Degradation bei Systemausfall?
- Benachrichtigungsketten?

### 10. Lernfähigkeit & Adaptation
**MCU-Referenz:** Jarvis lernt aus Tonys Verhalten, passt sich an, wird über die Filme hinweg immer besser.
- Wie lernt der reale Jarvis?
- Correction Memory — lernt er aus Fehlern?
- Langzeit-Adaptation?
- Feedback-Loop-Qualität?

### 11. Multi-Room-Awareness & Follow-Me
**MCU-Referenz:** Jarvis ist überall im Haus präsent, folgt Tony von Raum zu Raum, passt Lautstärke und Kontext an.
- Follow-Me Audio?
- Raum-basierte Kontextanpassung?
- Nahtlose Übergänge zwischen Räumen?

### 12. Erklärbarkeit & Transparenz
**MCU-Referenz:** "Sir, may I remind you that you've been awake for 72 hours?" — Jarvis erklärt seine Empfehlungen, nennt Gründe.
- XAI / Explainability?
- Begründet Jarvis seine Entscheidungen?
- Nachvollziehbarkeit für den Benutzer?

---

## Ausgabeformat

Für **jeden Vergleichspunkt** verwende dieses Format:

```
## [Kategorie-Name]

### MCU-Jarvis Benchmark
[Was MCU-Jarvis in dieser Kategorie kann, mit konkreten Szenen-Referenzen]

### MindHome-Jarvis Status: XX%
[Prozent-Bewertung mit Begründung]

### Code-Verifizierung
**[V1] Erste Analyse:**
- Datei: `pfad/zur/datei.py` — Funktion `xyz()` (Zeile XX-YY)
- [Was die Implementierung tatsächlich tut]
- [Stärken der aktuellen Implementierung]

**[V2] Zweite Analyse:**
- [Was beim zweiten Durchgang auffiel]
- [Fehlende Edge Cases, TODOs, nicht aufgerufener Code]
- [Vergleich: Was existiert vs. was fehlt]

### Was fehlt zum MCU-Level
1. [Konkreter Punkt 1] — [Warum es fehlt und wie gravierend]
2. [Konkreter Punkt 2] — ...

### Konkrete Verbesserungsvorschläge
1. **[Titel]** — [Genau was zu tun ist, in welcher Datei, welche Logik]
   - Aufwand: [Klein/Mittel/Groß]
   - Impact: [Wie viel Prozent es zur MCU-Bewertung hinzufügen würde]
2. ...

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
[Definiere 3-5 messbare Kriterien die erfüllt sein müssen, damit dieses Feature als MCU-Level gilt]
- [ ] Kriterium 1 — [konkret, testbar, messbar]
- [ ] Kriterium 2 — ...
- [ ] Kriterium 3 — ...
```

---

## Phase 2: Implementierungs-Roadmap

Nachdem alle Kategorien analysiert sind, erstelle eine **priorisierte Implementierungs-Roadmap** die sicherstellt, dass am Ende MCU-Level erreicht wird.

### Abhängigkeitsgraph
Erstelle einen Abhängigkeitsgraph: Welche Verbesserungen müssen VOR anderen umgesetzt werden?
Beispiel: Bessere Sprecherkennung (7) muss vor personalisiertem Butler-Verhalten (8) kommen.

```
Abhängigkeiten:
[Feature A] ──→ [Feature B] ──→ [Feature C]
                                 ↗
[Feature D] ────────────────────┘
```

### Sprint-Plan
Teile alle Verbesserungen in Sprints auf (jeder Sprint = 1 zusammenhängende Arbeitseinheit):

```
### Sprint 1: [Thema] — Fundament
**Ziel:** [Was nach diesem Sprint MCU-Level sein soll]
**Vorher:** XX% Gesamt | **Nachher (Ziel):** XX% Gesamt

1. [Aufgabe 1] — Datei: `pfad`, Funktion: `xyz()`
   - Was genau zu tun ist (Pseudocode oder konkrete Beschreibung)
   - Akzeptanzkriterium das erfüllt sein muss
2. [Aufgabe 2] — ...

**Validierung nach Sprint 1:**
- [ ] [Test/Prüfung die bestätigt dass das Ziel erreicht ist]
- [ ] [Regressions-Check: Was darf NICHT kaputtgegangen sein]
```

### Reihenfolge-Prinzipien
Sortiere die Sprints nach diesen Regeln:
1. **Abhängigkeiten zuerst** — Fundamente vor Features die darauf aufbauen
2. **Höchster Impact zuerst** — Was den Gesamt-Score am meisten hebt
3. **Quick Wins vorziehen** — Kleine Änderungen mit großem Effekt vor Großprojekten
4. **Risiko minimieren** — Sicherheitskritische Verbesserungen vor Nice-to-haves
5. **Vernetzung maximieren** — Features die andere Features besser machen zuerst

---

## Phase 3: Implementierungsanweisungen

Für **jede einzelne Verbesserung** in der Roadmap, erstelle eine **umsetzungsfertige Anweisung**:

```
### Aufgabe: [Titel]
**Sprint:** X | **Priorität:** [Kritisch/Hoch/Mittel] | **Aufwand:** [Klein/Mittel/Groß]

#### Ist-Zustand
- Datei: `pfad/zur/datei.py`
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

#### Akzeptanzkriterien
- [ ] [Testbares Kriterium 1]
- [ ] [Testbares Kriterium 2]
- [ ] Kein Regressions-Bruch in bestehenden Tests
- [ ] Feature ist in settings.yaml konfigurierbar

#### Risiken & Vorsichtsmaßnahmen
- [Was könnte schiefgehen beim Umsetzen]
- [Was muss vorher gesichert/getestet werden — Produktivsystem!]
```

**WICHTIG:** Die Anweisungen müssen so konkret sein, dass ein Entwickler (oder ein Code-LLM) sie **ohne Rückfragen** umsetzen kann. Keine vagen Formulierungen wie "verbessere die Logik" — sondern "füge in `anticipation.py` Zeile 340 eine Gewichtung hinzu die den Wochentag berücksichtigt".

---

## Phase 4: Abschluss & Gesamtbewertung

### Gesamtübersicht

```
| Kategorie                    | Aktuell | Nach Umsetzung | Status-Tag      | Sprint |
|------------------------------|---------|----------------|-----------------|--------|
| Natürliche Konversation      | XX%     | XX%            | [VERBESSERBAR]  | 1,3    |
| Persönlichkeit & Humor       | XX%     | XX%            | [OK]            | -      |
| ...                          | ...     | ...            | ...             | ...    |
| **GESAMT**                   | **XX%** | **XX%**        |                 |        |
```

### Fehlende Features (komplett neu zu bauen)
| Feature | MCU-Referenz | Aufwand | Sprint |
|---------|--------------|---------|--------|
| ...     | ...          | ...     | ...    |

### Top-10 Quick Wins (Impact/Aufwand-Verhältnis)
1. [Aufgabe] — **+X%** Gesamt, Aufwand: Klein, Sprint: X
2. ...

### Kritischer Pfad zum MCU-Level
Liste die **minimale Menge an Änderungen** die nötig ist um von aktuell XX% auf ≥90% zu kommen.
Was ist der kürzeste Weg? Was kann weggelassen werden und was ist unverzichtbar?

### Fazit
- **Aktueller Stand:** XX% MCU-Level — [Einschätzung in 1 Satz]
- **Erreichbar nach Umsetzung:** XX% — [Was dann noch fehlt]
- **Größte Stärke:** [Was der reale Jarvis besser macht als erwartet]
- **Größte Schwäche:** [Was am weitesten vom MCU-Level entfernt ist]
- **Empfehlung:** [Womit sofort starten, was kann warten]

---

## Phase 5: Re-Validierung (nach Implementierung)

> **Diesen Abschnitt NACH der Umsetzung der Sprints als separaten Prompt verwenden.**

Wenn die Verbesserungen implementiert sind, führe diesen Prompt erneut aus mit dem Zusatz:

"Ich habe die Verbesserungen aus der vorherigen Analyse implementiert. Führe jetzt eine **Re-Validierung** durch:
1. Prüfe jeden Sprint — sind alle Akzeptanzkriterien erfüllt?
2. Berechne die neuen Prozent-Werte pro Kategorie
3. Gibt es neue Lücken die durch die Änderungen sichtbar geworden sind?
4. Was fehlt noch zum MCU-Level?
5. Erstelle einen neuen Sprint-Plan für die verbleibenden Lücken."

---

*Dieser Prompt wurde erstellt am 2026-03-21 für das MindHome J.A.R.V.I.S. Projekt.*
