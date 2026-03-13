# Prompt 10 — Final Validation: Zero-Bug Abschluss

> **Abhängigkeit**: Nach P09b (letzter Fix-Prompt). Nutzt ALLE Kontext-Blöcke.
> **Dauer**: ~30–45 Minuten
> **Fokus**: Sicherstellen dass NULL offene Bugs existieren. Kein Finding übersprungen. Alles gefixt.

---

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Deine einzige Aufgabe: **Verifiziere dass das Projekt bug-frei ist.** Jeder offene Bug wird JETZT gefixt.

---

## Grundregel

**Am Ende dieses Prompts darf KEIN EINZIGER Bug offen sein.**

- Kein "das machen wir im nächsten Durchlauf"
- Kein "Empfehlung für später"
- Kein "MENSCH-Eskalation" ohne dass DU zuerst den besten Fix versucht hast
- Jedes Finding wird entweder GEFIXT oder mit BEWEIS als FALSE_POSITIVE markiert

---

## Phase 1: OFFEN-Bugs sammeln

Lies alle Kontext-Blöcke der vorherigen Prompts und sammle **JEDEN** offenen Bug:

```
# Alle OFFEN-Einträge aus den Kontext-Blöcken zusammentragen
```

| # | Bug | Severity | Datei:Zeile | Aus Prompt | Status |
|---|---|---|---|---|---|
| 1 | ? | 🔴/🟠/🟡 | ? | P0X | OFFEN |
| ... | ... | ... | ... | ... | ... |

**Erwartetes Ergebnis:** Vollständige Liste ALLER offenen Bugs aus P01–P09b.

---

## Phase 2: Jeden Bug verifizieren

Für jeden offenen Bug:

### Schritt 1 — Existiert der Bug noch?

```
Read: [betroffene Datei] offset=[Zeile - 10] limit=30
```

| Ergebnis | Aktion |
|---|---|
| Bug existiert noch | → Weiter zu Schritt 2 (Fixen) |
| Bug wurde bereits indirekt gefixt | → Als `INDIREKT_GEFIXT` markieren mit Beweis |
| Code wurde gelöscht/refactored | → Als `OBSOLET` markieren mit Beweis |
| Bug war ein Fehlalarm | → Als `FALSE_POSITIVE` markieren mit Begründung |

### Schritt 2 — Bug fixen

```
# Kontext verstehen
Read: [Datei] offset=[relevanter Bereich]
Grep: pattern="[relevante Funktion/Variable]" path="." output_mode="content"

# Fix anwenden
Edit: [Datei] old_string="[buggy code]" new_string="[fixed code]"

# Verifizieren
Bash: cd assistant && python -m pytest --tb=short -q 2>&1 | tail -10
```

### Schritt 3 — Wenn der Fix nicht trivial ist

Wenn ein Bug tiefere Analyse braucht:

1. **Lies MEHR Code** — nicht aufgeben nach einer Datei:
```
Grep: pattern="[Funktion die den Bug verursacht]" path="." output_mode="content"
Read: [jede Datei die die Funktion nutzt]
```

2. **Verstehe die Abhängigkeitskette:**
```
Grep: pattern="import.*[betroffenes_modul]|from.*[betroffenes_modul]" path="." output_mode="content"
```

3. **Wähle den minimalen Fix:**
- Kein Over-Engineering
- Kein Refactoring als Ausrede
- Einfachster Fix der den Bug behebt

4. **Triff die Entscheidung SELBST:**
- Du hast genug Kontext aus 10+ Prompts
- Du kennst die Architektur
- Wähle den besten Fix und dokumentiere WARUM

---

## Phase 3: Vollständiger Regression-Test

Nach ALLEN Fixes:

```bash
# Alle Tests
cd assistant && python -m pytest --tb=short -q

# Coverage
cd assistant && python -m pytest --cov=assistant --cov-report=term-missing --cov-branch -q

# Statische Analyse (wenn ruff installiert)
ruff check assistant/ addon/ speech/ shared/ 2>/dev/null || echo "ruff nicht installiert"
```

**Akzeptanzkriterien:**
- □ Alle Tests bestehen (0 failures)
- □ Keine neuen Failures durch Fixes
- □ Coverage ≥ 60% gesamt
- □ Kein kritisches Modul unter 50%

---

## Phase 4: Frische Bug-Suche (Doppel-Check)

Auch wenn alle bekannten Bugs gefixt sind — suche aktiv nach **neuen** Bugs die durch die Fixes entstanden sein könnten:

### Quick-Scan (5 Minuten)

```
# Fehlende awaits (häufigster Bug-Typ)
Grep: pattern="= (self\.|await self\.)" path="assistant/assistant/brain.py" output_mode="content" head_limit=20

# Stille Fehler
Grep: pattern="except.*:\s*$|except.*pass" path="assistant/assistant/" output_mode="content" multiline=true head_limit=20

# None-Checks
Grep: pattern="\.get\(|\.get_" path="assistant/assistant/brain.py" output_mode="content" head_limit=20

# Import-Fehler (nach Refactoring)
Bash: cd assistant && python -c "import assistant" 2>&1

# Syntax-Check aller geänderten Dateien
Bash: cd assistant && python -m py_compile assistant/brain.py 2>&1
```

### Jeder neue Bug → sofort fixen

Nicht dokumentieren und weiterreichen — FIXEN.

---

## Phase 5: Security Final-Check

```
# Prompt Injection
Grep: pattern="f\"|f'" path="assistant/assistant/context_builder.py" output_mode="content"

# Hardcoded Secrets
Grep: pattern="password.*=.*\"|api_key.*=.*\"|token.*=.*\"|secret.*=.*\"" path="." output_mode="content"

# Dangerous Functions
Grep: pattern="eval\(|exec\(|os\.system\(|subprocess\.call\(|__import__" path="." output_mode="content"
```

Jeder Fund → sofort fixen oder als sicher belegen.

---

## Phase 6: Abschluss-Validierung

### Finale Checkliste

| # | Check | Status |
|---|---|---|
| 1 | Alle OFFEN-Bugs aus P01–P09b: gefixt oder mit Beweis als FALSE_POSITIVE | □ |
| 2 | Alle Tests bestehen | □ |
| 3 | Coverage ≥ 60% | □ |
| 4 | Keine neuen Bugs durch Fixes | □ |
| 5 | Security-Check bestanden | □ |
| 6 | Keine stille Fehler (except: pass) in Core-Modulen | □ |
| 7 | Keine print() in Produktionscode | □ |
| 8 | Keine hardcoded Secrets | □ |
| 9 | Alle Docker-Container buildbar | □ |
| 10 | README aktuell | □ |

### Zero-Bug Declaration

Wenn alle Checks bestanden:

```
╔══════════════════════════════════════════════╗
║  🎯 ZERO-BUG DECLARATION                     ║
║                                              ║
║  Alle {N} bekannten Bugs wurden gefixt.      ║
║  Frische Bug-Suche: {M} neue gefunden → {M}  ║
║  gefixt.                                     ║
║                                              ║
║  Tests: {X} passed, 0 failed                 ║
║  Coverage: {Y}%                              ║
║  Security: Clean                             ║
║                                              ║
║  Status: READY FOR PRODUCTION                ║
╚══════════════════════════════════════════════╝
```

---

## Wenn Bugs WIRKLICH nicht fixbar sind

Nur in diesen Ausnahmen darf ein Bug offen bleiben:

1. **Hardware-abhängig** — Bug tritt nur mit laufendem Redis/ChromaDB/Ollama auf und kann nicht aus Code allein verifiziert werden
2. **External API** — Bug in Drittanbieter-Paket (z.B. Ollama-Client Bug)
3. **Architektur-Limitation** — Fix würde >500 Zeilen Code ändern und hat hohes Regressions-Risiko

In jedem Fall:
- Dokumentiere den Bug mit **maximaler Präzision**
- Gib den **exakten Fix** an (was geändert werden muss)
- Erkläre warum du es **jetzt nicht tun kannst**
- Erstelle einen **Test** der den Bug verifiziert (damit er beim nächsten Durchlauf sofort gefunden wird)

---

## Output

Am Ende erstelle folgenden Block:

```
=== FINAL VALIDATION REPORT ===

BUGS GESAMT (aus allen Prompts): {N}

STATUS:
- GEFIXT: {A} ({A/N * 100}%)
- FALSE_POSITIVE: {B}
- INDIREKT_GEFIXT: {C}
- OBSOLET: {D}
- OFFEN (mit Begründung): {E}

FRISCHE BUG-SUCHE:
- Neue Bugs gefunden: {M}
- Davon gefixt: {M}

TESTS:
- Passed: {X}
- Failed: {Y}
- Coverage: {Z}%

SECURITY:
- Prompt Injection: [CLEAN/FIXED]
- Hardcoded Secrets: [CLEAN/FIXED]
- Dangerous Functions: [CLEAN/FIXED]

WENN OFFEN > 0:
- 🔴 [SEVERITY] Bug | Datei:Zeile | GRUND: [Hardware/External/Architektur]
  → EXAKTER FIX: [was geändert werden muss]
  → TEST: [Test-Code der den Bug verifiziert]

GEAENDERTE DATEIEN: [Vollständige Liste aller in diesem Prompt editierten Dateien]

ZERO-BUG STATUS: [ERREICHT / {E} BUGS VERBLEIBEN]
===================================
```
