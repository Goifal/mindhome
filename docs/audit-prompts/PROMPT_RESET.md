# Prompt RESET: Vorbereitung fuer den naechsten Audit-Durchlauf

## Rolle

Du bist der Audit-Koordinator. Du bereitest den naechsten Audit-Durchlauf vor, indem du den Status des vorherigen sicherst und eine priorisierte Bug-Restliste erstellst.

## LLM-Spezifisch (Qwen 3.5)

- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu hoeflichen Floskeln ("Natuerlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- character_hint in settings.yaml model_profiles nutzen fuer Anti-Floskel

## Wann verwenden

- Nach Prompt 07 (Sicherheit)
- Oder nach groesseren Code-Aenderungen zwischen Audit-Runden
- Oder wenn ein neuer Durchlauf gestartet werden soll

---

## Aufgabe

### Phase 1: Vorherigen Durchlauf zusammenfassen (10min)

1. Lies alle RESULT-Dateien in docs/audit-results/:
   - RESULT_01 bis RESULT_07 (oder welche existieren)

2. Erstelle eine Zusammenfassung:
   - Gesamt-Bugs gefunden
   - Davon gefixt
   - Davon offen (nach Severity)
   - Geaenderte Dateien (Gesamtzahl)

### Phase 2: Unfixte Bugs sammeln (15min)

1. Sammle alle OFFEN-Eintraege aus allen RESULT-Dateien
2. Sortiere nach Severity: KRITISCH → HOCH → MITTEL → NIEDRIG
3. Formatiere als priorisierte Checkliste:

```
## OFFENE BUGS AUS DURCHLAUF #N

### KRITISCH (X offen)
□ [Bug-Beschreibung] | Datei:Zeile | Grund warum nicht gefixt
□ ...

### HOCH (X offen)
□ ...

### MITTEL (X offen)
□ ...

### NIEDRIG (X offen)
□ ...
```

### Phase 3: Regressions-Check (10min)

1. Pruefe ob bereits gefixte Bugs NOCH gefixt sind:
   - Stichprobe: 5 KRITISCH-Fixes aus vorherigem Durchlauf
   - grep/Read um zu verifizieren dass der Fix noch vorhanden ist

2. Dokumentiere Regressionen:
```
### REGRESSIONEN
□ [Bug X war gefixt, ist jetzt wieder offen] | Datei:Zeile
```

### Phase 4: Delta-Checkliste erstellen (5min)

1. Erstelle die Checkliste fuer den naechsten Durchlauf:
   - Neue Code-Aenderungen seit letztem Audit (git log)
   - Neue Dateien die noch nicht auditiert wurden
   - Geaenderte Dateien die re-auditiert werden muessen

```
### NEUE/GEAENDERTE DATEIEN SEIT LETZTEM AUDIT
[git log --name-only seit letztem Audit-Commit]
```

### Phase 5: Reset bestaetigen

Schreibe das Ergebnis in: docs/audit-results/RESULT_RESET_DURCHLAUF_N.md

---

## Output-Format

```
=== RESET FUER DURCHLAUF #(N+1) ===

VORHERIGER DURCHLAUF: #N
  Bugs gefunden: X
  Bugs gefixt: Y (Z%)
  Bugs offen: W

OFFENE BUGS (priorisiert):
  KRITISCH: [Liste]
  HOCH: [Liste]
  MITTEL: [Anzahl, Details in RESULT_RESET]
  NIEDRIG: [Anzahl]

REGRESSIONEN: [Liste oder "keine"]

NEUE DATEIEN: [Liste]
GEAENDERTE DATEIEN: [Liste]

EMPFEHLUNG: [Welcher Prompt zuerst, basierend auf offenen Bugs]
===================================
```

---

## Erfolgs-Check

```
□ Alle RESULT-Dateien gelesen
□ Offene Bugs gesammelt und priorisiert
□ Regressions-Check durchgefuehrt (mind. 5 Stichproben)
□ Delta-Checkliste erstellt
□ RESULT_RESET_DURCHLAUF_N.md geschrieben
```
