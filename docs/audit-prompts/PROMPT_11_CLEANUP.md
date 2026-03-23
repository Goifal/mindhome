# Prompt 11: Cleanup — Result-Dateien aufräumen

> **Abhängigkeit**: Nach P10 (Final Validation).
> **Fokus**: Alle temporären Result-Dateien löschen. Nur eine `OPEN_BUGS.md` bleibt, falls Bugs offen sind.

---

## Warum Cleanup?

Die Result-Dateien in `docs/audit-results/` sind nach dem Durchlauf veraltet:
- Sie füllen den Kontext unnötig wenn Claude das Repo liest
- Git-History bewahrt sie sowieso auf
- Veraltete Results können zu falschen Annahmen im nächsten Durchlauf führen

---

## Aufgabe

### Schritt 1: OPEN_BUGS.md erstellen (falls Bugs offen)

Prüfe den FINAL VALIDATION REPORT aus P10. Falls `OFFEN > 0`:

```bash
# Erstelle OPEN_BUGS.md mit allen verbleibenden Bugs
```

Format:
```markdown
# Offene Bugs — Durchlauf #{N} ({Datum})

## Statistik
- Gefixt in diesem Durchlauf: {A}
- Verbleibend: {E}

## Offene Bugs

### 🔴 KRITISCH
| # | Bug | Datei:Zeile | Grund | Exakter Fix |
|---|---|---|---|---|
| 1 | Beschreibung | datei.py:123 | Hardware-abhängig | `code fix hier` |

### 🟠 HOCH
(gleiche Tabelle)

### 🟡 MITTEL
(gleiche Tabelle)

## Test-Status
- Passed: {X}
- Failed: {Y}
- Coverage: {Z}%
```

Falls `OFFEN == 0`: Keine `OPEN_BUGS.md` erstellen.

### Schritt 2: Result-Dateien löschen

```bash
# Alle Result-Dateien entfernen
rm -f docs/audit-results/RESULT_*.md
rm -f docs/audit-results/REPORT_*.md
rm -f docs/audit-results/P04*.md
rm -f docs/audit-results/RESULT_RESET_*.md

# Prüfen ob Verzeichnis leer ist (außer OPEN_BUGS.md)
ls docs/audit-results/
```

> **⚠️ NICHT löschen**: `OPEN_BUGS.md` (falls gerade erstellt)

### Schritt 3: Commit

```bash
git add docs/audit-results/
git commit -m "Cleanup: Audit-Results nach Durchlauf #{N} entfernt, OPEN_BUGS.md aktualisiert"
```

### Schritt 4: Verifikation

```
ls docs/audit-results/
# Erwartetes Ergebnis: nur OPEN_BUGS.md (oder leer wenn keine Bugs offen)
```

---

## Regeln

- **Lösche NUR Dateien in `docs/audit-results/`** — keine Prompts, keinen Code
- **Git-History bewahrt alles** — die Dateien sind nicht verloren, nur aus dem aktuellen Stand entfernt
- **OPEN_BUGS.md ist die einzige Datei die im nächsten Durchlauf gebraucht wird**

---

## Output

```
=== CLEANUP REPORT ===
GELOESCHT: {N} Result-Dateien ({X}KB)
OPEN_BUGS.md: [Erstellt mit {E} offenen Bugs / Nicht nötig — alle Bugs gefixt]
NAECHSTER SCHRITT: PROMPT_RESET.md für neuen Durchlauf
===================================
```
