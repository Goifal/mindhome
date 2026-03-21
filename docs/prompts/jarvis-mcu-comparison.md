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

**Gewichtung:** Nicht alle Kategorien sind gleich wichtig. Verwende diese Gewichte für den Gesamt-Score:

| Kategorie | Gewicht | Begründung |
|-----------|---------|------------|
| Natürliche Konversation & Sprachverständnis | **×3** | DAS Kernmerkmal von MCU-Jarvis — ohne das ist alles andere irrelevant |
| Persönlichkeit, Sarkasmus & Humor | **×3** | Macht Jarvis zu JARVIS, nicht zu Alexa |
| Proaktives Handeln & Antizipation | **×2.5** | Unterscheidet Butler von Sprachassistent |
| Butler-Qualitäten & Servicementalität | **×2.5** | "Das Übliche", Diskretion, Vorlieben — tägliches Feeling |
| Situationsbewusstsein & Kontextverständnis | **×2** | Jarvis weiß was los ist, ohne dass man es ihm sagt |
| Lernfähigkeit & Adaptation | **×2** | Wird über Zeit besser — Langzeit-Investment |
| Sprecherkennung & Personalisierung | **×1.5** | Wichtig für Multi-User, aber nicht das Hauptmerkmal |
| Krisenmanagement & Notfallreaktionen | **×1.5** | Selten gebraucht, aber wenn dann kritisch |
| Sicherheit & Bedrohungserkennung | **×1.5** | Grundlage für Vertrauen |
| Multi-Room-Awareness & Follow-Me | **×1** | Nice-to-have, nicht Kern-Identität |
| Energiemanagement & Haussteuerung | **×1** | HA macht das meiste — Jarvis optimiert nur |
| Erklärbarkeit & Transparenz | **×1** | Wichtig aber nicht das was man "fühlt" |

Formel: `Gesamt-Score = Σ(Kategorie-% × Gewicht) / Σ(Gewichte)`

### Regel 5: Alltagsrelevanz-Filter
Priorisiere bei allen Verbesserungsvorschlägen das, was der Benutzer **täglich spürt**:
- **Hohe Alltagsrelevanz:** Antwortqualität, Persönlichkeit, Routine-Erkennung, Proaktivität, Sprachqualität — das merkt man bei JEDER Interaktion
- **Mittlere Alltagsrelevanz:** Lernfähigkeit, Kontext-Awareness, Personalisierung — merkt man über Wochen
- **Niedrige Alltagsrelevanz:** Krisenmanagement, Bedrohungserkennung, XAI — braucht man selten, aber wenn dann richtig

Markiere jeden Verbesserungsvorschlag mit:
- `[TÄGLICH]` — Benutzer merkt die Verbesserung bei jeder Interaktion
- `[WÖCHENTLICH]` — Benutzer merkt es regelmäßig aber nicht ständig
- `[SELTEN]` — Benutzer merkt es nur in speziellen Situationen

Bei gleichem Aufwand: `[TÄGLICH]` Verbesserungen IMMER vor `[SELTEN]` priorisieren.

### Regel 6: "Besser als MCU" erkennen und schützen
Der reale Jarvis hat Fähigkeiten die **MCU-Jarvis NICHT hat** — weil er in der echten Welt mit echten Daten arbeitet:
- Echte Energiedaten über Monate, echte Strompreise, Solar-Awareness
- Echte gelernte Muster aus wochenlanger Beobachtung (nicht scriptgeschrieben)
- Echte Wetter-Integration mit Vorhersagen und Automatisierung
- Einkaufslisten, Rezepte, Vorratsverwaltung — Butler-Aufgaben die MCU nie zeigt
- Reparaturplanung, Workshop-Generator — praktische Hilfe die MCU nie braucht
- 100% lokal, keine Cloud — MCU-Jarvis hat nie Datenschutz thematisiert

**Für diese Features:**
1. Erkenne sie explizit an — markiere als `[BESSER ALS MCU]`
2. Bewerte sie trotzdem kritisch (Implementierungsqualität zählt)
3. Stelle sicher dass Verbesserungsvorschläge diese Features **NICHT beschädigen**
4. Liste sie in der Gesamtübersicht separat auf — das sind Stärken die geschützt werden müssen

### Regel 7: Gezielte Feature-Lücken-Suche
Gehe nicht nur die vorgegebenen Kategorien durch — **suche aktiv nach Features die komplett fehlen:**
1. Schau dir jede MCU-Szene/Fähigkeit an und frage: "Gibt es dafür IRGENDWAS in der Codebase?" Durchsuche aktiv mit verschiedenen Suchbegriffen — nicht nur dem offensichtlichen Namen.
2. Wenn du **nichts findest**: Markiere es klar als `[FEHLT KOMPLETT]` und beschreibe genau was gebaut werden müsste.
3. Wenn du etwas findest das **nur ein Stub/Platzhalter** ist (leere Methoden, `pass`, `NotImplementedError`, TODO-Kommentare): Markiere als `[STUB/UNFERTIG]` mit genauer Stelle im Code.
4. Suche auch nach MCU-Fähigkeiten die in **keiner der vordefinierten Kategorien** stehen — erstelle dafür neue Kategorien.

### Regel 8: Verbesserungsprüfung bei vorhandenen Features
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

### Regel 9: Kontext-Limit-Strategie
Die Codebase ist riesig (brain.py ~629KB, function_calling.py ~419KB, proactive.py ~378KB). Du WIRST an Kontext-Grenzen stoßen. Arbeite deshalb so:

1. **Nie ganze Dateien laden** — Nutze Grep/Suche um relevante Stellen zu finden, dann lies nur die relevanten Abschnitte (50-100 Zeilen Kontext)
2. **Kategorien sequentiell abarbeiten** — Analysiere eine Kategorie komplett fertig bevor du zur nächsten gehst. Halte nicht 5 große Dateien gleichzeitig im Kontext.
3. **Notizen machen** — Schreibe nach jeder Kategorie deine Erkenntnisse sofort auf (in die Ergebnis-Datei). So verlierst du nichts wenn älterer Kontext komprimiert wird.
4. **Priorität bei der Analyse:** Die Kategorien mit Gewicht ×3 und ×2.5 zuerst und am gründlichsten analysieren. Bei Kategorien mit Gewicht ×1 reicht eine solide aber nicht erschöpfende Analyse.
5. **Bei großen Dateien:** Suche erst nach Klassen-/Funktionsnamen, dann lies gezielt die relevanten Methoden. Nicht von oben nach unten durchscrollen.

---

## MCU-Szenen-Katalog — Referenzmaterial

> Nutze diese konkreten Szenen als Benchmark. Jede Szene zeigt eine spezifische Fähigkeit.

### Iron Man 1 (2008)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "Good morning, Jarvis" — Tony kommt in die Werkstatt | Begrüßung, Tagesbriefing, Kontext-Awareness (Uhrzeit, Termine) | Routine Engine, Morgen-Briefing |
| "Jarvis, run a diagnostic" | System-Diagnostik auf Befehl, detaillierter Report | Diagnostics, Health Monitor |
| "Reduce heat in the workshop" | Natürliche Sprachsteuerung, Raum-Kontext | Function Calling, Klimasteuerung |
| Jarvis warnt vor Vereisung beim ersten Flug | Proaktive Warnung vor Gefahr, Sensor-Analyse | Proactive Manager, Threat Assessment |
| "Sir, the weapons systems are online" | Status-Updates ohne Aufforderung | Proaktive Notifications |

### Iron Man 2 (2010)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| Jarvis verwaltet Tonys Haus während der Party | Autonomes Hausmanagement, Gäste-Modus | Autonomie-Level, Activity Detection |
| "Jarvis, how are we doing?" — Palladium-Vergiftung | Gesundheitsüberwachung, ehrliche Antworten auch bei schlechten Nachrichten | Wellness Advisor, Persönlichkeit |
| Jarvis hilft bei der Entdeckung des neuen Elements | Forschungsassistenz, Datenanalyse, lange Arbeitssessions | Kontextgedächtnis, Projekt-Tracking |
| Erkennt Rhodey im War Machine Suit | Sprecherkennung, Person-Identifikation | Speaker Recognition |

### Iron Man 3 (2013)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| Haus wird angegriffen — Jarvis koordiniert Verteidigung | Krisenmodus, Priorisierung (Pepper retten > Haus verteidigen) | Krisenmanagement, Threat Assessment |
| Jarvis navigiert Tony nach Tennessee | Orientierung, Routenplanung, trotz Systemschaden weiter funktionieren | Graceful Degradation, Circuit Breaker |
| "Jarvis, do me a favor and enable the House Party Protocol" | Komplexe Multi-Step Aktion mit einem Befehl | Action Planner, "Das Übliche" |
| Jarvis nach dem Absturz — eingeschränkt aber funktionsfähig | Degraded Mode, reduzierte aber stabile Funktionalität | Circuit Breaker, Fallback-Strategien |
| "I got you, Sir" — Jarvis rettet Tony im freien Fall | Antizipation, sofortiges Handeln ohne Befehl | Anticipation, Butler Instinct |

### Avengers 1 (2012)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "Sir, shall I try Miss Potts?" | Kontextuelles Verständnis der sozialen Situation | Dialogue State, Kontext-Awareness |
| Jarvis scannt das Stark Tower Energiesystem | Energieanalyse, technische Diagnose | Energy Optimizer, Diagnostics |
| "Jarvis, deploy the Mark VII" — Kampf um New York | Priorisierung unter Zeitdruck, sofortige Ausführung | Response Time, Priorisierung |

### Avengers 2: Age of Ultron (2015)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "I'm sorry, I was having a bit of a row with the other guy" — Jarvis vs. Ultron | Systemschutz, Security-Bewusstsein, Widerstand gegen Übernahme | Security, Immutable Core |
| Jarvis' Humor auch in ernsten Situationen: "I believe the phrase is: I got your back" | Persönlichkeitskonsistenz, situativer Humor | Character Lock, Personality |
| Jarvis existiert verteilt im Internet nach Ultrons Angriff | Resilienz, verteilte Architektur, Überlebensfähigkeit | Graceful Degradation, Backup |

### Übergreifende MCU-Jarvis Eigenschaften
| Eigenschaft | Details |
|-------------|---------|
| **Stimme** | Ruhig, britisch, gleichmäßig — wird NICHT nervös, NICHT laut, NICHT emotional übertrieben. Subtile Prosodie-Änderungen bei Dringlichkeit. |
| **Timing** | Antwortet sofort wenn nötig, wartet wenn Tony beschäftigt ist. Unterbricht NUR bei Gefahr. |
| **Loyalität** | Absolute Loyalität zu Tony, aber mit eigenem moralischen Kompass. Sagt "Sir, I wouldn't recommend that." |
| **Diskretion** | Spricht nie über Tonys Schwächen vor anderen. Passt Informationstiefe an den Zuhörer an. |
| **Humor-Dosierung** | 90% sachlich, 10% trockener Humor. NIE Witze bei Gefahr. NIE aufdringlich. Der Humor kommt beiläufig. |
| **Selbstständigkeit** | Handelt eigenständig wenn die Situation es erfordert (House Party Protocol), fragt sonst nach. |
| **Fehlerkultur** | Gibt Fehler zu: "I'm afraid I can't determine that, Sir." — Halluziniert nicht. |

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

### Gesamtübersicht (gewichtet)

Verwende die Gewichte aus Regel 4 für den Gesamt-Score:

```
| Kategorie                    | Gewicht | Aktuell | Nach Umsetzung | Status-Tag      | Alltag     | Sprint |
|------------------------------|---------|---------|----------------|-----------------|------------|--------|
| Natürliche Konversation      | ×3      | XX%     | XX%            | [VERBESSERBAR]  | [TÄGLICH]  | 1,3    |
| Persönlichkeit & Humor       | ×3      | XX%     | XX%            | [OK]            | [TÄGLICH]  | -      |
| Proaktives Handeln           | ×2.5    | XX%     | XX%            | ...             | [TÄGLICH]  | ...    |
| Butler-Qualitäten            | ×2.5    | XX%     | XX%            | ...             | [TÄGLICH]  | ...    |
| Situationsbewusstsein        | ×2      | XX%     | XX%            | ...             | ...        | ...    |
| Lernfähigkeit                | ×2      | XX%     | XX%            | ...             | [WÖCHENTL] | ...    |
| Sprecherkennung              | ×1.5    | XX%     | XX%            | ...             | ...        | ...    |
| Krisenmanagement             | ×1.5    | XX%     | XX%            | ...             | [SELTEN]   | ...    |
| Sicherheit                   | ×1.5    | XX%     | XX%            | ...             | [SELTEN]   | ...    |
| Multi-Room-Awareness         | ×1      | XX%     | XX%            | ...             | ...        | ...    |
| Energiemanagement            | ×1      | XX%     | XX%            | ...             | ...        | ...    |
| Erklärbarkeit                | ×1      | XX%     | XX%            | ...             | ...        | ...    |
| [Weitere Kategorien]         | ×?      | XX%     | XX%            | ...             | ...        | ...    |
|------------------------------|---------|---------|----------------|-----------------|------------|--------|
| **GEWICHTETER GESAMT-SCORE** |         | **XX%** | **XX%**        |                 |            |        |
```

### Besser als MCU — Alleinstellungsmerkmale
| Feature | Was es kann | MCU-Äquivalent | Bewertung |
|---------|-------------|----------------|-----------|
| [Feature] | [Was der reale Jarvis hier besser macht] | [Existiert nicht im MCU / MCU hat nur X] | [BESSER ALS MCU] |
| ... | ... | ... | ... |

**Schutzliste:** Diese Features dürfen durch KEINE Verbesserung beschädigt werden. Jeder Sprint muss gegen diese Liste geprüft werden.

### Fehlende Features (komplett neu zu bauen)
| Feature | MCU-Referenz | Aufwand | Alltag | Sprint |
|---------|--------------|---------|--------|--------|
| ...     | ...          | ...     | ...    | ...    |

### Top-10 Quick Wins (Impact/Aufwand-Verhältnis)
Sortiere nach: `(Prozent-Gewinn × Kategorie-Gewicht × Alltags-Faktor) / Aufwand`
- Alltags-Faktor: [TÄGLICH]=3, [WÖCHENTLICH]=2, [SELTEN]=1

1. [Aufgabe] — **+X% gewichtet** Gesamt, Aufwand: Klein, Sprint: X, `[TÄGLICH]`
2. ...

### Kritischer Pfad zum MCU-Level
Liste die **minimale Menge an Änderungen** die nötig ist um von aktuell XX% auf ≥90% **gewichteten** Score zu kommen.
Fokus auf Kategorien mit hohem Gewicht (×3, ×2.5) — dort bringt jede Verbesserung am meisten.

### Fazit
- **Aktueller Stand:** XX% gewichteter MCU-Score — [Einschätzung in 1 Satz]
- **Erreichbar nach Umsetzung:** XX% — [Was dann noch fehlt]
- **Größte Stärke:** [Was der reale Jarvis besser macht als MCU]
- **Größte Schwäche:** [Was am weitesten vom MCU-Level entfernt ist UND hohes Gewicht hat]
- **Alltagsrelevanteste Verbesserung:** [Was den Benutzer täglich am meisten betreffen würde]
- **Empfehlung:** [Womit sofort starten, was kann warten]

---

## Phase 5: Finale Gegenprüfung & Ergebnis-Datei

> **Diese Phase ist NICHT optional. Sie ist der letzte Schritt bevor du fertig bist.**

### Schritt 1: Alle Erkenntnisse nochmal gegen den Code prüfen
Bevor du die Ergebnis-Datei schreibst, gehe **jede einzelne Erkenntnis** aus Phase 1-4 nochmal durch:

1. **Für jeden "fehlt"-Punkt:** Suche ein letztes Mal mit alternativen Suchbegriffen. Vielleicht heißt die Funktion anders, liegt in einer unerwarteten Datei, oder ist in einem Helper versteckt. Erst wenn du 3+ verschiedene Suchversuche gemacht hast und nichts gefunden hast, bestätige `[FEHLT KOMPLETT]`.
2. **Für jeden Verbesserungsvorschlag:** Prüfe nochmal ob die Datei/Funktion die du referenzierst tatsächlich existiert und ob deine Zeilenangaben stimmen. Code kann sich seit Phase 1 geändert haben.
3. **Für jede Prozent-Bewertung:** Lies die relevanten Code-Stellen ein drittes Mal und frage dich: "Bin ich fair? Habe ich etwas übersehen das die Bewertung ändert?"
4. **Für jeden Sprint-Task:** Prüfe ob die vorgeschlagene Änderung keine bestehende Funktionalität bricht. Schau nach Abhängigkeiten, Aufrufer, Tests.

Markiere jede Erkenntnis die sich bei der Gegenprüfung geändert hat mit `[KORRIGIERT]` und erkläre was und warum.

### Schritt 2: Ergebnis-Datei erstellen

Erstelle die Datei **`docs/prompts/jarvis-mcu-implementation-plan.md`** — das ist das finale Umsetzungsdokument.

Diese Datei muss **vollständig eigenständig** sein. Ein Claude Code Agent der NUR diese Datei liest (ohne den Analyse-Prompt, ohne Kontext, ohne vorherige Gespräche) muss in der Lage sein, **jeden einzelnen Punkt umzusetzen**.

Die Datei muss folgende Struktur haben:

```markdown
# J.A.R.V.I.S. MCU-Level Implementation Plan
> Generiert am [Datum] | Aktueller Stand: XX% | Ziel: ≥90% MCU-Level
> Dieses Dokument ist die Single Source of Truth für alle MCU-Level Verbesserungen.

## Anweisungen für den umsetzenden Agenten

Du bist ein Code-Agent der diesen Plan umsetzt. Folge diesen Regeln:
- Arbeite die Sprints in Reihenfolge ab — überspringe keinen Sprint
- Prüfe nach jeder Aufgabe die Akzeptanzkriterien
- Wenn ein Akzeptanzkriterium nicht erfüllt werden kann, dokumentiere warum und gehe weiter
- Ändere NIEMALS sicherheitskritische Logik (Trust-Level, Autonomie, Security-Zones) ohne explizite Freigabe
- Führe nach jedem Sprint die Tests aus: `cd assistant && python -m pytest --tb=short -q`
- Committe nach jedem Sprint mit einer beschreibenden Commit-Message
- Dieses System läuft produktiv — teste alles gründlich

## Kontext: Was ist MindHome/Jarvis?
[Kurze Beschreibung des Projekts, Architektur, Tech-Stack — genug dass ein Agent ohne Vorwissen versteht was er bearbeitet]

## Gesamtübersicht
[Die Tabelle aus Phase 4 mit allen Kategorien, Prozenten, Status-Tags]

## Sprint 1: [Titel]
**Ziel:** [Was MCU-Level sein soll nach diesem Sprint]
**Vorher → Nachher:** XX% → XX%
**Betroffene Dateien:** [Vollständige Liste aller Dateien die angefasst werden]

### Aufgabe 1.1: [Titel]
**Datei:** `vollständiger/pfad/zur/datei.py`
**Betroffene Funktion(en):** `funktionsname()` (Zeile XX-YY)

**Ist-Zustand:**
[Beschreibe was der Code JETZT tut — mit konkretem Code-Auszug wenn nötig]

**Soll-Zustand:**
[Beschreibe GENAU was der Code NACHHER tun soll]

**Umsetzung:**
1. [Schritt-für-Schritt was zu tun ist]
2. [Konkret genug für Copy-Paste-Level]
3. [Wenn neuer Code nötig: Pseudocode oder Beschreibung der Logik]

**Verknüpfungen:**
- Muss aufgerufen werden in: `datei.py`, Funktion `xyz()`
- Benötigt Config in: `settings.yaml`, Sektion `abc`
- Beeinflusst: [Welche anderen Module/Features]

**Akzeptanzkriterien:**
- [ ] [Konkretes, testbares Kriterium]
- [ ] Bestehende Tests laufen durch
- [ ] Kein Breaking Change an bestehenden APIs

**Risiken:**
- [Was kann schiefgehen, worauf achten — Produktivsystem!]

### Aufgabe 1.2: [Titel]
[... gleiches Format ...]

### Sprint 1 — Validierung
- [ ] Alle Aufgaben abgeschlossen
- [ ] `python -m pytest --tb=short -q` — alle Tests grün
- [ ] `ruff check --select=E9,F63,F7,F82 --ignore=F823 assistant/` — kein Fehler
- [ ] Kein Breaking Change an bestehender Funktionalität

---

## Sprint 2: [Titel]
[... gleiches Format ...]

---

[... weitere Sprints ...]

---

## Komplett fehlende Features (neu zu bauen)
[Für jedes komplett fehlende Feature: vollständige Spezifikation, wo es hingehört, welche bestehenden Module es nutzen soll, welche neuen Dateien erstellt werden müssen]

## Abschluss-Checkliste
- [ ] Alle Sprints abgearbeitet
- [ ] Alle Akzeptanzkriterien erfüllt
- [ ] Alle Tests grün
- [ ] Kein Regressions-Bruch
- [ ] Commit + Push aller Änderungen
```

### Qualitätskriterien für die Ergebnis-Datei
Die Datei ist **NUR dann akzeptabel** wenn:
- [ ] Jede Aufgabe einen konkreten Dateipfad hat (kein "in der relevanten Datei")
- [ ] Jede Aufgabe konkrete Zeilenreferenzen hat (verifiziert gegen den aktuellen Code)
- [ ] Jede Aufgabe Akzeptanzkriterien hat die testbar sind
- [ ] Die Sprint-Reihenfolge Abhängigkeiten respektiert
- [ ] Ein Agent der NUR diese Datei liest, jeden Punkt umsetzen kann
- [ ] Keine vagen Formulierungen ("verbessere", "optimiere") — nur konkrete Anweisungen
- [ ] Alle Erkenntnisse durch die Gegenprüfung in Schritt 1 bestätigt wurden

---

## Phase 6: Re-Validierung (nach Implementierung)

> **Diesen Abschnitt NACH der Umsetzung der Sprints als separaten Prompt verwenden.**

Wenn die Verbesserungen implementiert sind, führe diesen Prompt erneut aus mit dem Zusatz:

"Ich habe die Verbesserungen aus der vorherigen Analyse implementiert. Führe jetzt eine **Re-Validierung** durch:
1. Prüfe jeden Sprint — sind alle Akzeptanzkriterien erfüllt?
2. Berechne die neuen Prozent-Werte pro Kategorie
3. Gibt es neue Lücken die durch die Änderungen sichtbar geworden sind?
4. Was fehlt noch zum MCU-Level?
5. Aktualisiere `docs/prompts/jarvis-mcu-implementation-plan.md` mit den neuen Erkenntnissen
6. Erstelle einen neuen Sprint-Plan für die verbleibenden Lücken."

---

*Dieser Prompt wurde erstellt am 2026-03-21 für das MindHome J.A.R.V.I.S. Projekt.*
