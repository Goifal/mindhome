# Session 2: J.A.R.V.I.S. MCU vs. MindHome — Erweiterte Kategorien (×2 & ×1.5)

> **Verwendung:** Diesen Prompt an Claude Code geben. NUR Session 2 ausführen — danach stoppen.
> **Voraussetzung:** Session 1 muss abgeschlossen sein. Die Datei `docs/prompts/jarvis-mcu-implementation-plan.md` muss existieren.
> **Ergebnis:** Wird in die bestehende `docs/prompts/jarvis-mcu-implementation-plan.md` ergänzt.

---

## Deine Aufgabe

Du bist ein Elite-Software-Architekt und MCU-Experte. Du kennst J.A.R.V.I.S. aus dem Marvel Cinematic Universe (Iron Man 1-3, Avengers 1-2) in- und auswendig.

Du analysierst das MindHome-Projekt: einen realen KI-Assistenten namens **J.A.R.V.I.S.**, der ein Smart Home steuert.

**Dies ist Session 2 von 4.** Du analysierst die 5 Kategorien mit mittlerer Gewichtung:

| Kategorie | Gewicht | Verifizierung |
|-----------|---------|---------------|
| 5. Situationsbewusstsein & Kontextverständnis | **×2** | V1 Pflicht, V2 bei Auffälligkeiten |
| 6. Lernfähigkeit & Adaptation | **×2** | V1 Pflicht, V2 bei Auffälligkeiten |
| 7. Sprecherkennung & Personalisierung | **×1.5** | V1 Pflicht, V2 bei Auffälligkeiten |
| 8. Krisenmanagement & Notfallreaktionen | **×1.5** | V1 Pflicht, V2 bei Auffälligkeiten |
| 9. Sicherheit & Bedrohungserkennung | **×1.5** | V1 Pflicht, V2 bei Auffälligkeiten |

### Vorbereitung
1. **Lies zuerst** `docs/prompts/jarvis-mcu-implementation-plan.md` — verstehe was Session 1 bereits analysiert hat
2. Dann analysiere die 5 Kategorien dieser Session
3. Ergänze die Ergebnisse in der bestehenden Plan-Datei

---

## Regeln

### Regel 1: Nur realistische Fähigkeiten
Ignoriere alles aus dem MCU, was physisch unmöglich oder irrelevant für ein Smart Home ist:
- **IGNORIEREN:** Iron Man Suit steuern, Waffen, Hologramm-Displays, Vibranium-Forschung, Quantenphysik, SHIELD-Hacking, Ultron-Erschaffung, fliegende Drohnen bauen
- **RELEVANT:** Natürliche Konversation, Sarkasmus & Humor, proaktives Handeln, Situationsbewusstsein, Sicherheitsüberwachung, Energiemanagement, Haussteuerung, Persönlichkeit & Loyalität, Antizipation von Bedürfnissen, Multi-Room-Awareness, Sprecherkennung, Krisenmanagement, kontextuelle Intelligenz, Butler-Qualitäten

### Regel 2: Gewichtsbasierte Code-Verifizierung — Einzelverifizierung + Stichproben

Kategorien mit Gewicht ×2 und ×1.5:
1. **V1 — Vollständige Verifizierung:** Durchsuche die Codebase gezielt. Lies die tatsächliche Implementierung. Schau in Methoden rein, prüfe Logik und Bedingungen.
2. **V2 — Nur bei Auffälligkeiten:** Führe V2 nur durch, wenn V1 Verdachtsmomente liefert (unvollständige Implementierung, verdächtige TODOs, Code der nie aufgerufen wird).
   - Dokumentiere: `[V2 übersprungen — V1 unauffällig]` oder `[V2 durchgeführt — Grund: ...]`

### Regel 3: Tiefenanalyse — kein Oberflächliches Scannen
- Lies nicht nur die Datei-Header oder Klassen-Definitionen — **lies die tatsächliche Logik**
- Suche nach der **echten Implementierung**, nicht nur nach Platzhaltern
- Prüfe ob Features **tatsächlich verwendet werden** (werden sie im Brain aufgerufen? Gibt es Routes dafür?)
- Prüfe **Konfigurationen** in `settings.yaml` — sind Features aktiviert oder deaktiviert?
- Schaue in **Tests** — was wird getestet, was nicht?
- Suche nach **`# TODO`**, **`# FIXME`**, **`# HACK`**, **`pass`**, **`NotImplementedError`**

### Regel 4: Prozent-Bewertung
- **0-20%:** Grundidee existiert, aber kaum funktional
- **21-40%:** Basisfunktionalität vorhanden, aber weit entfernt vom MCU-Level
- **41-60%:** Solide Grundlage, aber spürbare Lücken
- **61-80%:** Gute Implementierung, fehlen Feinheiten und Tiefe
- **81-95%:** Nahe am MCU-Level, nur Details fehlen
- **96-100%:** Gleichwertig oder besser als MCU-Jarvis

Sei **ehrlich und kritisch**, nicht schmeichelnd.

**Gewichtung (Gesamtübersicht — alle 12 Kategorien):**

| Kategorie | Gewicht |
|-----------|---------|
| Natürliche Konversation & Sprachverständnis | **×3** |
| Persönlichkeit, Sarkasmus & Humor | **×3** |
| Proaktives Handeln & Antizipation | **×2.5** |
| Butler-Qualitäten & Servicementalität | **×2.5** |
| Situationsbewusstsein & Kontextverständnis | **×2** |
| Lernfähigkeit & Adaptation | **×2** |
| Sprecherkennung & Personalisierung | **×1.5** |
| Krisenmanagement & Notfallreaktionen | **×1.5** |
| Sicherheit & Bedrohungserkennung | **×1.5** |
| Multi-Room-Awareness & Follow-Me | **×1** |
| Energiemanagement & Haussteuerung | **×1** |
| Erklärbarkeit & Transparenz | **×1** |

Formel: `Gesamt-Score = Σ(Kategorie-% × Gewicht) / Σ(Gewichte)`

### Regel 5: Alltagsrelevanz-Filter
Markiere jeden Verbesserungsvorschlag mit:
- `[TÄGLICH]` — Benutzer merkt die Verbesserung bei jeder Interaktion
- `[WÖCHENTLICH]` — Benutzer merkt es regelmäßig aber nicht ständig
- `[SELTEN]` — Benutzer merkt es nur in speziellen Situationen

### Regel 6: "Besser als MCU" erkennen und schützen
Markiere als `[BESSER ALS MCU]` und stelle sicher dass Verbesserungsvorschläge diese Features **NICHT beschädigen**.

### Regel 7: Feature-Status markieren
- `[OK]` — Feature funktioniert gut
- `[VERBESSERBAR]` — hat klare Schwächen
- `[UNTERVERBUNDEN]` — nicht ausreichend vernetzt
- `[VERALTET]` — nutzt veraltete Patterns
- `[FEHLT KOMPLETT]` — nichts gefunden (nach 3+ Suchbegriffen)
- `[STUB/UNFERTIG]` — nur Platzhalter

### Regel 8: Kontext-Limit-Strategie
- **Nie ganze Dateien laden** — Grep/Suche nutzen, dann nur relevante Abschnitte (50-100 Zeilen)
- **Kategorien sequentiell abarbeiten**
- **Notizen sofort aufschreiben**
- **Bei großen Dateien:** Erst Funktionsnamen suchen, dann gezielt lesen

---

## MCU-Szenen-Katalog — Referenzmaterial

### Iron Man 1 (2008)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "Jarvis, run a diagnostic" | System-Diagnostik auf Befehl, detaillierter Report | Diagnostics, Health Monitor |
| Jarvis warnt vor Vereisung beim ersten Flug | Proaktive Warnung vor Gefahr, Sensor-Analyse | Proactive Manager, Threat Assessment |

### Iron Man 2 (2010)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| Jarvis verwaltet Tonys Haus während der Party | Autonomes Hausmanagement, Gäste-Modus | Autonomie-Level, Activity Detection |
| "Jarvis, how are we doing?" — Palladium-Vergiftung | Gesundheitsüberwachung, ehrliche Antworten | Wellness Advisor |
| Erkennt Rhodey im War Machine Suit | Sprecherkennung, Person-Identifikation | Speaker Recognition |

### Iron Man 3 (2013)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| Haus wird angegriffen — Jarvis koordiniert Verteidigung | Krisenmodus, Priorisierung (Pepper retten > Haus verteidigen) | Krisenmanagement, Threat Assessment |
| Jarvis navigiert Tony nach Tennessee | Trotz Systemschaden weiter funktionieren | Graceful Degradation, Circuit Breaker |
| Jarvis nach dem Absturz — eingeschränkt aber funktionsfähig | Degraded Mode, reduzierte aber stabile Funktionalität | Circuit Breaker, Fallback-Strategien |

### Avengers 1 (2012)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| Jarvis scannt das Stark Tower Energiesystem | Energieanalyse, technische Diagnose | Energy Optimizer, Diagnostics |

### Avengers 2: Age of Ultron (2015)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| Jarvis vs. Ultron — Systemschutz | Security-Bewusstsein, Widerstand gegen Übernahme | Security, Immutable Core |
| Jarvis existiert verteilt nach Ultrons Angriff | Resilienz, verteilte Architektur | Graceful Degradation, Backup |

### Übergreifende MCU-Jarvis Eigenschaften
| Eigenschaft | Details |
|-------------|---------|
| **Stimme** | Ruhig, britisch, gleichmäßig — subtile Prosodie-Änderungen bei Dringlichkeit |
| **Timing** | Antwortet sofort wenn nötig, wartet wenn Tony beschäftigt ist. Unterbricht NUR bei Gefahr |
| **Selbstständigkeit** | Handelt eigenständig wenn nötig, fragt sonst nach |
| **Fehlerkultur** | Gibt Fehler zu — halluziniert nicht |

---

## Vergleichskategorien (nur Session 2)

### 5. Situationsbewusstsein & Kontextverständnis (Gewicht: ×2)
**MCU-Referenz:** Jarvis weiß immer was im Haus passiert — Energiestatus, wer wo ist, aktuelle Bedrohungen, Wetter, Termine — alles gleichzeitig.
- Wie umfassend ist das Kontextbild?
- Werden alle Datenquellen verknüpft?
- Echtzeit-Updates oder Cache-Delays?
- Kreuzreferenz-Fähigkeit (Wetter + Fenster + Heizung)?

### 6. Lernfähigkeit & Adaptation (Gewicht: ×2)
**MCU-Referenz:** Jarvis lernt aus Tonys Verhalten, passt sich an, wird über die Filme hinweg immer besser.
- Wie lernt der reale Jarvis?
- Correction Memory — lernt er aus Fehlern?
- Langzeit-Adaptation?
- Feedback-Loop-Qualität?

### 7. Sprecherkennung & Personalisierung (Gewicht: ×1.5)
**MCU-Referenz:** Jarvis erkennt Tony sofort, unterscheidet zwischen Pepper, Rhodey, und Fremden. Passt Verhalten an die Person an.
- Wie zuverlässig ist die Sprecherkennung?
- Personalisierte Reaktionen pro Bewohner?
- Gäste-Erkennung vs. Bewohner?
- Multi-User-Szenarien?

### 8. Krisenmanagement & Notfallreaktionen (Gewicht: ×1.5)
**MCU-Referenz:** Bei Angriffen auf das Haus (Iron Man 3) koordiniert Jarvis die Verteidigung, priorisiert Menschenleben, bleibt unter Druck funktionsfähig.
- Notfall-Playbooks?
- Priorisierung bei Multi-Krisen?
- Graceful Degradation bei Systemausfall?
- Benachrichtigungsketten?

### 9. Sicherheit & Bedrohungserkennung (Gewicht: ×1.5)
**MCU-Referenz:** "Sir, I'm detecting an unauthorized entry." — Jarvis erkennt Einbrüche, ungewöhnliche Aktivitäten, Systemkompromittierungen sofort.
- Wie gut ist die Bedrohungserkennung?
- Ambient Audio (Glasbruch, Alarme)?
- Reaktionsgeschwindigkeit?
- Eskalationsketten?

---

## Ausgabeformat

Für **jeden Vergleichspunkt** verwende dieses Format:

```
## [Kategorie-Name]

### MCU-Jarvis Benchmark
[Was MCU-Jarvis in dieser Kategorie kann, mit konkreten Szenen-Referenzen]

### MindHome-Jarvis Status: XX%

### Code-Verifizierung
**[V1] Erste Analyse:**
- Datei: `pfad/zur/datei.py` — Funktion `xyz()` (Zeile XX-YY)
- [Was die Implementierung tatsächlich tut]

**[V2]:** [V2 übersprungen — V1 unauffällig] ODER [V2 durchgeführt — Grund: ...]

### Was fehlt zum MCU-Level
1. [Konkreter Punkt] — [Warum und wie gravierend]

### Konkrete Verbesserungsvorschläge
1. **[Titel]** — [Genau was zu tun ist]
   - Aufwand: [Klein/Mittel/Groß]
   - Impact: [Prozent-Gewinn]
   - Alltag: [TÄGLICH/WÖCHENTLICH/SELTEN]

### Akzeptanzkriterien
- [ ] Kriterium 1
- [ ] Kriterium 2
```

---

## Ergebnis-Datei aktualisieren

Öffne **`docs/prompts/jarvis-mcu-implementation-plan.md`** und:

1. **Ergänze** die 5 neuen Kategorien-Analysen nach den bestehenden 4 aus Session 1
2. **Aktualisiere** den Fortschritts-Tracker (9 von 12 Kategorien analysiert)
3. **Ergänze** die Schutzliste falls neue "Besser als MCU" Features gefunden wurden
4. **Aktualisiere** den Teilergebnis-Score (jetzt mit 9 Kategorien berechenbar)

---

*Session 2 von 4. Nächste Session: `jarvis-mcu-session-3.md` (Kategorien 10-12 + Roadmap)*
