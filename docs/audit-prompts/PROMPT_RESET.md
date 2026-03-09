# Prompt RESET: Neuer Audit-Durchlauf vorbereiten

## Zweck

Dieser Prompt wird **vor** einem neuen Durchlauf der Prompt-Serie (P1–P7) verwendet. Er sorgt dafür, dass:

1. **Alle vorherigen Kontext-Blöcke verworfen** werden
2. Die **Ergebnisse des letzten Durchlaufs** kompakt zusammengefasst werden (als Vergleichsbasis)
3. Der neue Durchlauf mit **frischem Blick** startet — ohne Bias aus der vorherigen Analyse

---

## Wann verwenden?

- **Nach Prompt 7** eines Durchlaufs, wenn Fixes implementiert wurden und du prüfen willst ob sie wirken
- **Nach größeren Code-Änderungen** zwischen zwei Audit-Runden
- **Wenn der Context Window voll ist** und du eine neue Konversation starten musst

---

## Anweisung an das LLM

> **Du startest jetzt einen NEUEN, FRISCHEN Audit-Durchlauf der Jarvis-Codebase.**
>
> ### Was das bedeutet:
>
> 1. **VERGISS alle bisherigen Kontext-Blöcke** (KONTEXT AUS PROMPT 1–7). Sie sind veraltet.
> 2. **VERGISS alle bisherigen Bewertungen** — Module die vorher "okay" waren, können jetzt Bugs haben (und umgekehrt).
> 3. **VERGISS alle bisherigen Bug-Listen** — du findest die Bugs NEU im aktuellen Code.
> 4. **Lies JEDE Datei NEU** — auch wenn du sie im letzten Durchlauf gelesen hast. Der Code hat sich geändert.
> 5. **Keine Annahmen** aus dem vorherigen Durchlauf übernehmen. Alles verifizieren.
>
> ### Was du BEHALTEN sollst:
>
> - Dein **Wissen über die Architektur** (3 Services, Shared-Module, HA-Integration)
> - Die **Prompt-Struktur** (P1–P7 und was jeder Prompt erwartet)
> - Die **Gründlichkeits-Pflicht** (jede Datei öffnen, jede Zeile lesen, Code-Referenzen)
>
> ### Dein Auftrag jetzt:
>
> Fasse den **vorherigen Durchlauf** kompakt zusammen (als Vergleichsbasis für den neuen Durchlauf), dann bestätige dass du bereit bist für Prompt 1.

---

## Aufgabe

### Schritt 1 — Vorherigen Durchlauf zusammenfassen

Erstelle eine kompakte **Zusammenfassung des letzten Durchlaufs**. Wenn du keinen vorherigen Durchlauf in dieser Konversation hattest, überspringe diesen Schritt.

```
## ZUSAMMENFASSUNG VORHERIGER DURCHLAUF (Durchlauf #X)

### Datum / Kontext
[Wann wurde der letzte Durchlauf gemacht? Was war der Anlass?]

### Architektur-Bewertung (P1)
- God-Objects: [brain.py / main.py — Status]
- Kritischste Konflikte: [Top 3]
- Architektur-Entscheidung: [Was wurde empfohlen/umgesetzt?]

### Memory-Status (P2)
- Root Cause: [Was war das Hauptproblem?]
- Fix: [Was wurde implementiert?]
- Status: [Funktioniert / Teilweise / Offen]

### Flow-Status (P3)
| Flow | Status im letzten Durchlauf |
|---|---|
| 1: Sprach-Input → Antwort | ✅/⚠️/❌ |
| 2: Proaktive Benachrichtigung | ✅/⚠️/❌ |
| 3: Morgen-Briefing | ✅/⚠️/❌ |
| 4: Autonome Aktion | ✅/⚠️/❌ |
| 5: Persönlichkeits-Pipeline | ✅/⚠️/❌ |
| 6: Memory-Abruf | ✅/⚠️/❌ |
| 7: Speech-Pipeline | ✅/⚠️/❌ |
| 8: Addon-Automation | ✅/⚠️/❌ |
| 9: Domain-Assistenten | ✅/⚠️/❌ |
| 10: Workshop-System | ✅/⚠️/❌ |
| 11: Boot-Sequenz | ✅/⚠️/❌ |
| 12: File-Upload & OCR | ✅/⚠️/❌ |
| 13: WebSocket-Streaming | ✅/⚠️/❌ |

### Bug-Statistik (P4)
- Gesamt: X Bugs (🔴 X, 🟠 X, 🟡 X, 🟢 X)
- Davon behoben in P6: X
- Offen geblieben: X
- Security-Findings: X (davon behoben: X)

### Persönlichkeit (P5)
- MCU-Score: X/10
- Kritischste Inkonsistenz: [Beschreibung]
- Config-Probleme: [Anzahl]

### Harmonisierung (P6)
- Änderungen durchgeführt: X
- Architektur-Entscheidungen: [brain.py → ?, Memory → ?, Priority → ?]
- Offene Punkte: [Liste]

### Test & Deployment (P7)
- Tests: X bestanden / X fehlgeschlagen
- Docker: ✅/❌
- Resilience-Lücken: [Anzahl]
```

### Schritt 2 — Delta-Checkliste erstellen

Erstelle eine Liste von **Punkten die im neuen Durchlauf besonders beachtet** werden sollen:

```
## DELTA-CHECKLISTE FÜR NEUEN DURCHLAUF

### Aus letztem Durchlauf offen gebliebene Punkte
- [ ] [Beschreibung] — [Welcher Prompt prüft das?]
- [ ] ...

### Bereiche die sich seit dem letzten Durchlauf geändert haben
- [ ] [Datei/Modul] — [Was wurde geändert?]
- [ ] ...

### Neue Risiken durch die Änderungen aus P6
- [ ] [Beschreibung] — [Könnte neue Bugs eingeführt haben]
- [ ] ...
```

### Schritt 3 — Reset bestätigen

Bestätige mit dieser Aussage:

```
✅ RESET ABGESCHLOSSEN — Bereit für Durchlauf #X

Vorheriger Durchlauf zusammengefasst: Ja/Nein (kein vorheriger vorhanden)
Delta-Checkliste erstellt: Ja/Nein
Alle Kontext-Blöcke verworfen: Ja
Frischer Blick aktiv: Ja

→ Bitte starte jetzt mit PROMPT_01_ARCHITEKTUR.md
```

---

## Für separate Konversationen (Option B)

Wenn du den Reset in einer **neuen Konversation** machst und die Ergebnisse des vorherigen Durchlaufs manuell einfügen musst:

1. Kopiere die **Zusammenfassung** aus dem Ende der alten Konversation hier rein:

```
[HIER ZUSAMMENFASSUNG AUS DEM VORHERIGEN DURCHLAUF EINFÜGEN]
```

2. Das LLM erstellt daraus die Delta-Checkliste und startet frisch.

---

## Regeln

- **KEINE Ergebnisse aus dem vorherigen Durchlauf als "gegeben" annehmen** — alles neu verifizieren
- **Jede Datei neu lesen** — der Code hat sich geändert
- **Vergleiche aktiv** — wenn im letzten Durchlauf ein Bug bei `brain.py:123` war, prüfe ob er jetzt behoben ist
- **Neue Bugs suchen** — Fixes können neue Probleme eingeführt haben (Regressions)
- **Nicht nur die geänderten Stellen prüfen** — auch "stabile" Module können durch Änderungen in anderen Modulen betroffen sein
- Die Delta-Checkliste ist ein **Leitfaden**, kein Limit — der neue Durchlauf ist genauso gründlich wie der erste

---

## Durchlauf-Nummerierung

Halte fest welcher Durchlauf das ist:

| Durchlauf | Datum | Fokus | Ergebnis |
|---|---|---|---|
| #1 | ? | Erstanalyse | ? Bugs gefunden, ? behoben |
| #2 | ? | Verifikation nach Fixes | ? neue Bugs, ? Regressions |
| #3 | ? | ... | ... |

> Diese Tabelle hilft den Fortschritt über mehrere Durchläufe zu tracken.
