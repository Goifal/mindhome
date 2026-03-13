# PROMPT RESET — Neuer Audit-Durchlauf vorbereiten

## ZIEL

Frischer Start fuer einen neuen Audit-Durchlauf (P01-P07). Vorherige Ergebnisse kompakt zusammenfassen, alle Kontext-Bloecke verwerfen, unfixte Bugs als Checkliste uebernehmen.

## LLM-SPEZIFISCH (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

## WANN VERWENDEN

- **Nach PROMPT_07** eines Durchlaufs
- **Nach groesseren Code-Aenderungen** zwischen Audit-Runden
- **Neue Claude-Code-Session** (Context Window voll)

### Claude Code Hinweis

1. Beende die aktuelle Session
2. Starte neue Session im Projekt-Root (`/home/user/mindhome`)
3. Uebergib diesen PROMPT_RESET als erste Nachricht
4. Danach: PROMPT_01_ARCHITEKTUR_FLOWS.md

---

## ANWEISUNG

> **Du startest einen NEUEN, FRISCHEN Audit-Durchlauf.**
>
> 1. **VERGISS** alle bisherigen Kontext-Bloecke (P01-P07). Sie sind veraltet.
> 2. **VERGISS** alle bisherigen Bewertungen.
> 3. **Lies JEDE Datei NEU** — der Code hat sich geaendert.
> 4. **Keine Annahmen** aus dem vorherigen Durchlauf uebernehmen.
>
> **BEHALTE:**
> - Wissen ueber die Architektur (3 Services, brain.py als Zentrale)
> - Die Prompt-Struktur (P01-P07)
> - Die Gruendlichkeits-Pflicht

---

## SCHRITT 1: Vorherigen Durchlauf zusammenfassen

Falls ein vorheriger Durchlauf existiert, fasse ihn kompakt zusammen:

```
## ZUSAMMENFASSUNG DURCHLAUF #X

### Analyse-Phase
#### Architektur (P01)
- Kritischste Konflikte: [Top 3 mit Status]

#### Memory (P02)
- Fakten-Abruf: [Funktioniert / Nicht]
- Memory-Prioritaet: [Gefixt? Status]

#### Flows (P03a + P03b)
- Core-Flows 1–7: [Welche funktionieren, welche nicht]
- Extended-Flows 8–13: [Kollisionen gefunden?]

#### Bug-Jagd (P04a + P04b + P04c)
- Gesamt: X Bugs (KRITISCH: X, HOCH: X, MITTEL: X, NIEDRIG: X)
- Security-Findings: [Top 3]
- Performance: [Latenz-Budget eingehalten?]

#### Persoenlichkeit (P05)
- MCU-Score: X/10
- System-Prompt: [Token-Anzahl]
- Config-Inkonsistenzen: [Anzahl]

### Fix-Phase
#### Stabilisierung (P06a)
- Kritische Bugs gefixt: X von Y
- Memory repariert: [Ja/Nein]

#### Architektur (P06b)
- Konflikte aufgeloest: X von Y
- Flows repariert: [Welche]

#### Charakter (P06c)
- Persoenlichkeit harmonisiert: [Ja/Nein]
- Dead Code entfernt: [Anzahl Dateien]

#### Haertung (P06d)
- Security-Luecken geschlossen: X von Y
- Resilience implementiert: [Welche Szenarien]

#### Geraetesteuerung (P06e)
- Tool-Calling: [Zuverlaessig / Unzuverlaessig]
- Deterministic Fallback: [Erweitert / Nicht]
- System-Prompt Tool-Pflicht: [Prominent / Begraben]

#### TTS & Response (P06f)
- Meta-Leakage: ["speak" in TTS? Gefixt?]
- Pre-TTS-Filter: [Implementiert / Nicht]

### Verifikation
#### Testing (P07a)
- Tests bestanden: X von Y
- OFFEN-Bug-Validierung: X bestaetigt, Y gefixt, Z false-positive

#### Deployment (P07b)
- Docker Build: [Erfolgreich / Fehlgeschlagen]
- Performance: [Latenz gemessen?]
```

## SCHRITT 2: Unfixte Bugs als Checkliste

**KRITISCH:** Uebernimm ALLE unfixten Bugs aus den OFFEN-Bloecken von P06a–P06f als Checkliste. Diese haben HOECHSTE Prioritaet im neuen Durchlauf.

Sammle die OFFEN-Eintraege aus allen Kontext-Bloecken und sortiere nach Eskalations-Kategorie:

```
## UNFIXTE BUGS AUS DURCHLAUF #X

### 🔴 KRITISCH — MENSCH (Autonome Entscheidung getroffen)
- [ ] [Bug-Beschreibung] — Datei:Zeile — ENTSCHEIDUNG: [was wurde entschieden + warum]
  → Im naechsten Durchlauf: Ergebnis der Entscheidung verifizieren

### 🔴🟠 ARCHITEKTUR_NOETIG (Groesserer Umbau erforderlich)
- [ ] [Bug-Beschreibung] — Datei:Zeile — Grund: [warum Architektur-Umbau]
  → Im naechsten Durchlauf: P06b (Architektur) priorisiert behandeln

### 🟠🟡 NAECHSTER_PROMPT (Thematisch verschoben, nicht aufgegriffen)
- [ ] [Bug-Beschreibung] — Datei:Zeile — Ursprungs-Prompt: [P06x]
  → Im naechsten Durchlauf: Gezielt im richtigen Prompt aufgreifen
```

**Regel: Kein Bug verschwindet.** Jeder OFFEN-Eintrag aus P06a–P06f MUSS in dieser Liste auftauchen. Wenn ein Bug in P07a als "doch gefixt" oder "false positive" erkannt wurde, dokumentiere das explizit.

## SCHRITT 3: Regressions-Check

Pruefe ob bereits gefixte Bugs noch gefixt sind:

```
## REGRESSIONS-CHECK

Fuer JEDEN Fix aus dem vorherigen Durchlauf:
1. Lies die Datei an der Fix-Stelle
2. Pruefe ob der Fix noch vorhanden ist
3. Wenn revertiert → zurueck auf die Unfixte-Liste

Ergebnis:
- Fixes intakt: X von Y
- Regressions gefunden: [Liste]
```

## SCHRITT 4: Delta-Checkliste

```
## DELTA-CHECKLISTE

### Offen gebliebene Punkte
- [ ] [Beschreibung] — [Welcher Prompt prueft das?]

### Bereiche die sich geaendert haben
- [ ] [Datei/Modul] — [Was wurde geaendert?]

### Neue Risiken durch Aenderungen
- [ ] [Beschreibung] — [Koennte neue Bugs eingefuehrt haben]
```

## SCHRITT 5: Reset bestaetigen

```
RESET ABGESCHLOSSEN — Bereit fuer Durchlauf #X

Vorheriger Durchlauf zusammengefasst: Ja/Nein
Unfixte Bugs uebernommen: X Bugs
Regressions-Check: X intakt, Y revertiert
Delta-Checkliste erstellt: Ja/Nein
Alle Kontext-Bloecke verworfen: Ja

→ Starte jetzt mit PROMPT_01_ARCHITEKTUR.md
```

---

## REGELN

- **KEINE Ergebnisse aus dem vorherigen Durchlauf als "gegeben" annehmen** — alles neu verifizieren
- **Jede Datei neu lesen** — der Code hat sich geaendert
- **Vergleiche aktiv** — pruefen ob vorherige Bugs behoben sind
- **Neue Bugs suchen** — Fixes koennen Regressions eingefuehrt haben
- Die Delta-Checkliste ist ein **Leitfaden**, kein Limit

---

## DURCHLAUF-TRACKING

| Durchlauf | Datum | Bugs gefunden | Bugs gefixt | Regressions |
|---|---|---|---|---|
| #1 | ? | ? | ? | ? |
| #2 | ? | ? | ? | ? |
| #3 | ? | ? | ? | ? |

---

## PROMPT-REIHENFOLGE

| Nr | Datei | Fokus |
|----|-------|-------|
| 00 | PROMPT_00_OVERVIEW.md | Architektur-Ueberblick + Modul-Karte |
| 01 | PROMPT_01_ARCHITEKTUR.md | Analyse: Konflikte A-F |
| 02 | PROMPT_02_MEMORY.md | Analyse + Fix: Memory-System (5 kritische Bugs) |
| 03a | PROMPT_03a_FLOWS_CORE.md | Analyse: 7 Core-Flows |
| 03b | PROMPT_03b_FLOWS_EXTENDED.md | Analyse: 6 Extended-Flows + Kollisionen |
| 04a | PROMPT_04a_BUGS_CORE.md | Bug-Finding: Core-Module (13 Fehlerklassen) |
| 04b | PROMPT_04b_BUGS_EXTENDED.md | Bug-Finding: Extended-Module |
| 04c | PROMPT_04c_BUGS_ADDON_SECURITY.md | Bug-Finding: Addon + Security |
| 05 | PROMPT_05_PERSONALITY.md | Analyse: MCU-Authentizitaet + Config |
| 06a | PROMPT_06a_STABILISIERUNG.md | Fix: Kritische Bugs (mit Code-Templates) |
| 06b | PROMPT_06b_ARCHITEKTUR.md | Fix: Architektur-Konflikte |
| 06c | PROMPT_06c_CHARAKTER.md | Fix: Persoenlichkeit + Anti-Floskel |
| 06d | PROMPT_06d_HAERTUNG.md | Fix: Security + Resilience + Addon |
| 06e | PROMPT_06e_GERAETESTEUERUNG.md | Fix: Tool-Calling + System-Prompt |
| 06f | PROMPT_06f_TTS_RESPONSE.md | Fix: speak-Filter + Meta-Leakage |
| 07a | PROMPT_07a_TESTING.md | Testing + Coverage |
| 07b | PROMPT_07b_DEPLOYMENT.md | Docker + Deployment |
| 08a | PROMPT_08a_CODEQUALITAET.md | Analyse: Docs, Dependencies, CI/CD, Lokalisierung |
| 08b | PROMPT_08b_BETRIEB.md | Analyse: Multi-User, Frontend, Monitoring, Persistenz |
| 09a | PROMPT_09a_FIX_CODEQUALITAET.md | Fix: Alle P08a Findings beheben |
| 09b | PROMPT_09b_FIX_BETRIEB.md | Fix: Alle P08b Findings beheben |
| 10 | PROMPT_10_FINAL_VALIDATION.md | Zero-Bug: Alle offenen Bugs fixen + Abschluss |
| RESET | PROMPT_RESET.md | Naechster Durchlauf vorbereiten |

---

## OUTPUT

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
ZUSAMMENFASSUNG: [Kompakte Zusammenfassung des vorherigen Durchlaufs]
UNFIXTE BUGS: [Anzahl, Top 3 kritischste]
REGRESSIONS: [Anzahl, welche]
DELTA: [Was hat sich geaendert]
NAECHSTER SCHRITT: Starte PROMPT_00_OVERVIEW.md
=====================================
```
