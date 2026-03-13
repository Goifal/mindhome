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

### Architektur (P01)
- Kritischste Konflikte: [Top 3 mit Status]
- Core-Flows: [Welche funktionieren, welche nicht]

### Memory (P02)
- Fakten-Abruf: [Funktioniert / Nicht]
- Conversation-History: [limit=3 gefixt? → limit=10?]
- Memory-Prioritaet: [3 → 1 gefixt?]

### Geraetesteuerung (P03)
- Tool-Calling: [Zuverlaessig / Unzuverlaessig]
- Deterministic Fallback: [Erweitert / Nicht]
- System-Prompt Tool-Pflicht: [Prominent / Begraben]

### TTS & Response (P04)
- Meta-Leakage: ["speak" in TTS? Gefixt?]
- Pre-TTS-Filter: [Implementiert / Nicht]
- Banned Phrases: [Erweitert / Nicht]

### Bug-Fixes (P05)
- Gesamt: X Bugs (KRITISCH: X, HOCH: X, MITTEL: X)
- Gefixt: X
- Offen: X

### Persoenlichkeit (P06)
- System-Prompt: [Token-Anzahl, MCU-Score X/10]
- Floskeln gefiltert: [Ja/Nein]

### Sicherheit (P07)
- Security-Fixes: X von 5
- Resilience: [Welche Szenarien abgedeckt]
```

## SCHRITT 2: Unfixte Bugs als Checkliste

**KRITISCH:** Uebernimm ALLE unfixten Bugs aus dem vorherigen Durchlauf als Checkliste. Diese haben HOECHSTE Prioritaet im neuen Durchlauf.

```
## UNFIXTE BUGS AUS DURCHLAUF #X

### KRITISCH (MUSS gefixt werden)
- [ ] [Bug-Beschreibung] — Datei:Zeile — Grund warum nicht gefixt
- [ ] ...

### HOCH (SOLLTE gefixt werden)
- [ ] [Bug-Beschreibung] — Datei:Zeile — Grund
- [ ] ...

### MITTEL (KANN gefixt werden)
- [ ] [Bug-Beschreibung] — Datei:Zeile — Grund
- [ ] ...
```

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

→ Starte jetzt mit PROMPT_01_ARCHITEKTUR_FLOWS.md
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

## NEUE PROMPT-REIHENFOLGE

| Nr | Datei | Fokus |
|----|-------|-------|
| 01 | PROMPT_01_ARCHITEKTUR_FLOWS.md | Analyse: Konflikte + Core-Flows |
| 02 | PROMPT_02_MEMORY.md | Fix: Memory-Integration + Fakten-Abruf |
| 03 | PROMPT_03_GERAETESTEUERUNG.md | Fix: Tool-Calling + System-Prompt |
| 04 | PROMPT_04_TTS_RESPONSE.md | Fix: speak-Filter + Meta-Leakage |
| 05 | PROMPT_05_BUGFIXES.md | Fix: Systematische Bug-Fixes (max 20) |
| 06 | PROMPT_06_PERSOENLICHKEIT.md | Fix: MCU-Charakter + Config |
| 07 | PROMPT_07_SICHERHEIT.md | Fix: Top-5 Security + Resilience |
| RESET | PROMPT_RESET.md | Naechster Durchlauf vorbereiten |

---

## OUTPUT

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
ZUSAMMENFASSUNG: [Kompakte Zusammenfassung des vorherigen Durchlaufs]
UNFIXTE BUGS: [Anzahl, Top 3 kritischste]
REGRESSIONS: [Anzahl, welche]
DELTA: [Was hat sich geaendert]
NAECHSTER SCHRITT: Starte PROMPT_01_ARCHITEKTUR_FLOWS.md
=====================================
```
