# Session 1: J.A.R.V.I.S. MCU vs. MindHome — Kern-Kategorien (×3 & ×2.5)

> **Verwendung:** Diesen Prompt an Claude Code geben. NUR Session 1 ausführen — danach stoppen.
> **Scope:** NUR den Assistenten analysieren (`assistant/` Verzeichnis). Das Add-on (`addon/`) ist NICHT Teil dieser Analyse.
> **Ergebnis:** Wird in `docs/prompts/jarvis-mcu-implementation-plan.md` geschrieben.

---

## Deine Aufgabe

Du bist ein Elite-Software-Architekt und MCU-Experte. Du kennst J.A.R.V.I.S. aus dem Marvel Cinematic Universe (Iron Man 1-3, Avengers 1-2) in- und auswendig — jede Szene, jeden Dialog, jede gezeigte Fähigkeit.

Du analysierst jetzt das MindHome-Projekt: einen realen KI-Assistenten namens **J.A.R.V.I.S.**, der ein Smart Home steuert. Dein Ziel ist ein schonungslos ehrlicher Vergleich zwischen dem MCU-Jarvis und diesem realen Jarvis.

**Dies ist Session 1 von 5.** Du analysierst die 4 wichtigsten Kategorien (höchste Gewichtung = größter Impact):

| Kategorie | Gewicht | Verifizierung |
|-----------|---------|---------------|
| 1. Natürliche Konversation & Sprachverständnis | **×3** | Volle Doppelverifizierung (V1+V2) |
| 2. Persönlichkeit, Sarkasmus & Humor | **×3** | Volle Doppelverifizierung (V1+V2) |
| 3. Proaktives Handeln & Antizipation | **×2.5** | Volle Doppelverifizierung (V1+V2) |
| 4. Butler-Qualitäten & Servicementalität | **×2.5** | Volle Doppelverifizierung (V1+V2) |

**Nach Abschluss:** Schreibe alle Ergebnisse sofort in `docs/prompts/jarvis-mcu-implementation-plan.md`. Die nächste Session baut darauf auf.

### Durchlauf-Nummer ermitteln
Lies den **Changelog** am Ende von `docs/prompts/jarvis-mcu-implementation-plan.md`. Zähle die bestehenden Durchlauf-Einträge. Dein Durchlauf ist **der nächste** (z.B. wenn der letzte `#2` war, bist du `#3`). Beim allerersten Durchlauf (kein Changelog vorhanden oder Datei existiert nicht) bist du `#1`.

---

## Regeln

### Regel 1: Nur realistische Fähigkeiten
Ignoriere alles aus dem MCU, was physisch unmöglich oder irrelevant für ein Smart Home ist:
- **IGNORIEREN:** Iron Man Suit steuern, Waffen, Hologramm-Displays, Vibranium-Forschung, Quantenphysik, SHIELD-Hacking, Ultron-Erschaffung, fliegende Drohnen bauen
- **RELEVANT:** Natürliche Konversation, Sarkasmus & Humor, proaktives Handeln, Situationsbewusstsein, Sicherheitsüberwachung, Energiemanagement, Haussteuerung, Persönlichkeit & Loyalität, Antizipation von Bedürfnissen, Multi-Room-Awareness, Sprecherkennung, Krisenmanagement, kontextuelle Intelligenz, Butler-Qualitäten

### Regel 2: Gewichtsbasierte Code-Verifizierung — Volle Doppelverifizierung (V1+V2)

Alle 4 Kategorien in dieser Session haben Gewicht ×3 oder ×2.5 — daher volle Doppelverifizierung:

1. **V1 — Erste Verifizierung:** Durchsuche die Codebase gezielt nach der relevanten Funktionalität. Lies die tatsächliche Implementierung — nicht nur Dateinamen oder Klassennamen. Schau in die Methoden rein, prüfe die Logik, lies die Bedingungen.
2. **V2 — Zweite Verifizierung:** Gehe den Code ein zweites Mal durch, diesmal aus einem anderen Blickwinkel. Suche nach Edge Cases, fehlenden Features, unvollständigen Implementierungen, TODOs, auskommentiertem Code, oder Stellen wo die Funktion zwar existiert aber nicht aufgerufen wird.
3. **Dokumentiere beide Verifizierungen:**
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

Bei gleichem Aufwand: `[TÄGLICH]` Verbesserungen IMMER vor `[SELTEN]` priorisieren.

### Regel 6: "Besser als MCU" erkennen und schützen
Der reale Jarvis hat Fähigkeiten die **MCU-Jarvis NICHT hat**. Für diese Features:
1. Erkenne sie explizit an — markiere als `[BESSER ALS MCU]`
2. Bewerte sie trotzdem kritisch (Implementierungsqualität zählt)
3. Stelle sicher dass Verbesserungsvorschläge diese Features **NICHT beschädigen**

### Regel 7: Gezielte Feature-Lücken-Suche
- Suche aktiv mit **3+ verschiedenen Suchbegriffen** (Synonyme, alternative Funktionsnamen)
- `[FEHLT KOMPLETT]` — wenn nichts gefunden wird
- `[STUB/UNFERTIG]` — wenn nur Platzhalter existieren (leere Methoden, `pass`, `NotImplementedError`)

### Regel 8: Verbesserungsprüfung bei vorhandenen Features
Markiere jedes vorhandene Feature mit:
- `[OK]` — Feature funktioniert gut, kaum Verbesserungsbedarf
- `[VERBESSERBAR]` — Feature existiert, hat aber klare Schwächen
- `[UNTERVERBUNDEN]` — Feature existiert, ist aber nicht ausreichend mit anderen Modulen vernetzt
- `[VERALTET]` — Feature existiert, nutzt aber veraltete Patterns

### Regel 9: Kontext-Limit-Strategie
- **Nie ganze Dateien laden** — Grep/Suche nutzen, dann nur relevante Abschnitte lesen (50-100 Zeilen)
- **Kategorien sequentiell abarbeiten** — eine Kategorie komplett fertig bevor zur nächsten
- **Notizen sofort aufschreiben** — nach jeder Kategorie Ergebnisse in die Plan-Datei schreiben
- **Bei großen Dateien:** Erst Klassen-/Funktionsnamen suchen, dann gezielt relevante Methoden lesen

### Regel 10: Inkrementelles Schreiben — NIEMALS alles auf einmal
> **KRITISCH:** Claude Code friert ein oder trunkiert bei großen Write-Aufrufen (>400 Zeilen).
> Die Plan-Datei MUSS in kleinen Abschnitten geschrieben werden.

**Schreibstrategie:**
1. **Erstanlage (Write-Tool):** Nur den Header schreiben (Status-Legende, Fortschritts-Tracker, Schutzliste + ein Platzhalter-Anker am Ende). Maximal ~40 Zeilen. Beispiel-Anker am Dateiende:
   ```
   <!-- NEXT_CATEGORY -->
   ```
2. **Pro Kategorie (Edit-Tool):** Nach jeder fertig analysierten Kategorie sofort per Edit den Platzhalter `<!-- NEXT_CATEGORY -->` ersetzen durch:
   - Die komplette Kategorie-Analyse im **exakten Ausgabeformat** (siehe "Ausgabeformat" weiter unten)
   - Gefolgt von einem neuen `<!-- NEXT_CATEGORY -->` Platzhalter für die nächste Kategorie
3. **Changelog (Edit-Tool):** Am Ende den letzten `<!-- NEXT_CATEGORY -->` Platzhalter durch den Changelog-Eintrag ersetzen
4. **Niemals die gesamte Datei neu schreiben** — immer nur den neuen Abschnitt per Edit einfügen

**Das Ausgabeformat (MCU-Benchmark, Status, V1/V2, Verbesserungsvorschläge, Akzeptanzkriterien) bleibt exakt gleich** — nur die Schreibmethode ändert sich (Edit statt Write). Inhaltlich und strukturell muss jede Kategorie genauso detailliert und vollständig sein wie bei einem einzelnen großen Write.

**Beispiel für den Edit-Aufruf pro Kategorie:**
```
old_string: "<!-- NEXT_CATEGORY -->"
new_string: "## 1. Natürliche Konversation & Sprachverständnis (×3)\n\n### MCU-Jarvis Benchmark\n...[vollständige Analyse]...\n\n<!-- NEXT_CATEGORY -->"
```

---

## MCU-Szenen-Katalog — Referenzmaterial

### Iron Man 1 (2008)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "Good morning, Jarvis" — Tony kommt in die Werkstatt | Begrüßung, Tagesbriefing, Kontext-Awareness (Uhrzeit, Termine) | Routine Engine, Morgen-Briefing |
| "Reduce heat in the workshop" | Natürliche Sprachsteuerung, Raum-Kontext | Function Calling, Klimasteuerung |
| Jarvis warnt vor Vereisung beim ersten Flug | Proaktive Warnung vor Gefahr, Sensor-Analyse | Proactive Manager, Threat Assessment |

### Iron Man 2 (2010)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| Jarvis verwaltet Tonys Haus während der Party | Autonomes Hausmanagement, Gäste-Modus | Autonomie-Level, Activity Detection |
| "Jarvis, how are we doing?" — Palladium-Vergiftung | Gesundheitsüberwachung, ehrliche Antworten auch bei schlechten Nachrichten | Wellness Advisor, Persönlichkeit |
| Jarvis hilft bei der Entdeckung des neuen Elements | Forschungsassistenz, Datenanalyse, lange Arbeitssessions | Kontextgedächtnis, Projekt-Tracking |

### Iron Man 3 (2013)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "Jarvis, do me a favor and enable the House Party Protocol" | Komplexe Multi-Step Aktion mit einem Befehl | Action Planner, "Das Übliche" |
| "I got you, Sir" — Jarvis rettet Tony im freien Fall | Antizipation, sofortiges Handeln ohne Befehl | Anticipation, Butler Instinct |

### Avengers 2: Age of Ultron (2015)
| Szene | Fähigkeit | Relevanz |
|-------|-----------|----------|
| "I believe the phrase is: I got your back" | Persönlichkeitskonsistenz, situativer Humor | Character Lock, Personality |

### Übergreifende MCU-Jarvis Eigenschaften
| Eigenschaft | Details |
|-------------|---------|
| **Stimme** | Ruhig, britisch, gleichmäßig — subtile Prosodie-Änderungen bei Dringlichkeit |
| **Timing** | Antwortet sofort wenn nötig, wartet wenn Tony beschäftigt ist. Unterbricht NUR bei Gefahr |
| **Loyalität** | Absolute Loyalität, aber mit eigenem moralischen Kompass |
| **Diskretion** | Passt Informationstiefe an den Zuhörer an |
| **Humor-Dosierung** | 90% sachlich, 10% trockener Humor. NIE Witze bei Gefahr |
| **Selbstständigkeit** | Handelt eigenständig wenn nötig, fragt sonst nach |
| **Fehlerkultur** | Gibt Fehler zu — halluziniert nicht |

---

## Vergleichskategorien (nur Session 1)

### 1. Natürliche Konversation & Sprachverständnis (Gewicht: ×3)
**MCU-Referenz:** Jarvis versteht Kontext über lange Gespräche, ironische Bemerkungen, implizite Anweisungen ("mach mal alles fertig"), Unterbrechungen, und spricht flüssig natürliches Englisch mit perfekter Prosodie.
- Wie natürlich sind die Dialoge des realen Jarvis?
- Versteht er Kontext über mehrere Turns?
- Kann er mit vagen Anweisungen umgehen?
- Wie ist die STT/TTS-Qualität?

### 2. Persönlichkeit, Sarkasmus & Humor (Gewicht: ×3)
**MCU-Referenz:** "I do apologize, Sir, but I'm not certain what you're asking me to do." — trockener britischer Humor, nie aufdringlich, situationsabhängig, verstummt bei Krisen.
- Wie authentisch ist die Persönlichkeit?
- Variiert der Humor situationsabhängig?
- Gibt es Character Consistency über Sessions hinweg?
- Krisenmodus — verstummt der Humor wirklich?

### 3. Proaktives Handeln & Antizipation (Gewicht: ×2.5)
**MCU-Referenz:** Jarvis warnt Tony vor Gefahren bevor er fragt, bereitet Dinge vor die Tony brauchen wird, denkt voraus.
- Wie gut antizipiert der reale Jarvis?
- Wie intelligent sind die proaktiven Vorschläge?
- False-Positive-Rate?
- Timing der Vorschläge?

### 4. Butler-Qualitäten & Servicementalität (Gewicht: ×2.5)
**MCU-Referenz:** Jarvis ist der perfekte Butler — diskret, loyal, merkt sich Vorlieben, bietet Hilfe an ohne aufdringlich zu sein, weiß wann er schweigen soll.
- Quiet Hours / Silence Matrix?
- Erinnerung an Vorlieben?
- "Das Übliche" — Routine-Erkennung?
- Diskretion und Datenschutz?

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
   - Alltag: [TÄGLICH/WÖCHENTLICH/SELTEN]
2. ...

### Akzeptanzkriterien — Wann ist dieses Feature "MCU-Level"?
- [ ] Kriterium 1 — [konkret, testbar, messbar]
- [ ] Kriterium 2 — ...
- [ ] Kriterium 3 — ...
```

---

## Ergebnis-Datei

Schreibe alle Ergebnisse in **`docs/prompts/jarvis-mcu-implementation-plan.md`**.

Wenn die Datei **noch nicht existiert**, erstelle sie mit diesem Header:

```markdown
# J.A.R.V.I.S. MCU-Level Implementation Plan
> Erstellt am [Datum] | Letzter Durchlauf: Session 1 am [Datum]
> Aktueller Stand: XX% (Teilergebnis — 4 von 12 Kategorien analysiert)
> Dieses Dokument ist die Single Source of Truth für alle MCU-Level Verbesserungen.

## Status-Legende
- `[ ]` — Offen, noch nicht umgesetzt
- `[~]` — Teilweise erledigt
- `[x]` — Vollständig erledigt und verifiziert
- `⏭️` — Obsolet
- `🆕` — Neu hinzugefügt

## Fortschritts-Tracker
| Session | Datum | Kategorien | Aufgaben |
|---------|-------|------------|----------|
| 1       | [Datum] | 1-4 (×3/×2.5) | XX |

## Schutzliste — Besser als MCU (NICHT beschädigen!)
[Hier eintragen was gefunden wird]
```

Dann füge die 4 Kategorien-Analysen im Ausgabeformat ein.

### Folge-Durchläufe (Plan-Datei existiert bereits)

Wenn die Datei bereits existiert, arbeitest du **inkrementell statt komplett neu**:

1. **Lies die bestehende Plan-Datei** und identifiziere den aktuellen Stand der Kategorien 1-4
2. **Prüfe per `git diff`** welche Dateien sich seit dem letzten Durchlauf geändert haben:
   ```bash
   git log --oneline -10  # Finde den letzten Durchlauf-Commit
   git diff --name-only HEAD~X  # X = Commits seit letztem Durchlauf
   ```
3. **Kategorien mit Code-Änderungen:** Volle Neuanalyse (V1+V2)
4. **Kategorien ohne Code-Änderungen:** Stichproben-Prüfung (V1 für 2-3 Schlüsselstellen), Status beibehalten wenn nichts auffällt
5. **Erledigtes markieren:** Prüfe jede Aufgabe gegen den aktuellen Code:
   - `[ ]` → `[x]` wenn umgesetzt: `✅ Erledigt am [Datum] — Durchlauf #X`
   - `[ ]` → `[~]` wenn teilweise: `[~] Teilweise erledigt — [Was noch fehlt]`
   - Prüfe ob Akzeptanzkriterien **tatsächlich** erfüllt sind (nicht blind abhaken!)
6. **Neue Erkenntnisse ergänzen:** Markiere mit `🆕 Hinzugefügt in Durchlauf #X`
7. **Veraltetes anpassen:**
   - Zeilenreferenzen aktualisieren → markiere mit `🔄`
   - Obsolete Aufgaben → markiere mit `⏭️ Obsolet — [Grund]`
8. **Prozent-Bewertung** der Kategorien 1-4 neu berechnen
9. **Changelog am Ende der Datei ergänzen:**
   ```
   ### Durchlauf #X — Session 1 — [Datum]
   - XX Aufgaben als erledigt markiert
   - XX neue Aufgaben hinzugefügt
   - XX Zeilenreferenzen aktualisiert
   - Kategorien 1-4 Score: [vorher → nachher]
   ```

**NIEMALS bestehende Einträge löschen** — nur Status-Updates, Ergänzungen und Markierungen.

---

*Session 1 von 5. Nächste Session: `jarvis-mcu-session-2.md` (Kategorien 5-9)*
