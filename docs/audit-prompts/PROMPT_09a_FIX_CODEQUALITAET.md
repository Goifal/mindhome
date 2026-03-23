# Prompt 09a — Fix: Code-Qualität Findings beheben

> **Abhängigkeit**: Nach P08a (Code-Qualität Analyse). Nutzt den Kontext-Block aus P08a.
> **Dauer**: ~30–60 Minuten
> **Fokus**: Alles fixen was P08a gefunden hat. Kein Finding bleibt offen.

---

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Du fixst systematisch alle Code-Qualitäts-Probleme die in Prompt 08a identifiziert wurden.

---

## Kontext aus vorherigen Prompts

> **Automatisch**: Lies die Ergebnisse der vorherigen Analyse-Prompts:

```
Read: docs/audit-results/RESULT_08a_CODEQUALITAET.md
```

> Falls eine Datei nicht existiert → überspringe sie. Wenn KEINE Result-Dateien existieren, nutze Kontext-Blöcke aus der Konversation oder starte mit Prompt 01.

---

## Grundregel

**Analysieren war gestern. Heute wird gefixt.**

Für jedes Finding aus P08a:
1. **Lies den Code** an der betroffenen Stelle
2. **Fix den Code** direkt mit Edit/Write
3. **Verifiziere** dass der Fix korrekt ist
4. Wenn du **nicht genug Kontext** hast → Lies mehr Code (Grep, Read) bis du genug weißt
5. Wenn der Fix **Architektur-Änderungen** braucht → Triff die beste Entscheidung selbst, dokumentiere WARUM

> **Kein Finding wird übersprungen.** Falls ein Fix andere Findings bricht: (1) Fix reverten, (2) Abhängigkeit dokumentieren, (3) beide Findings zusammen lösen. Wenn ein Fix nicht möglich ist, muss der GRUND dokumentiert und eskaliert werden.

---

## Phase Gate: Regression-Check

Bevor du anfängst:
```bash
cd assistant && python -m pytest --tb=short -q 2>&1 | tail -20
```
→ Ergebnis notieren als **BASELINE**

Nach jedem Fix-Block (alle 3-5 Fixes):
```bash
cd assistant && python -m pytest --tb=short -q 2>&1 | tail -20
```
→ Vergleichen mit Baseline. **Neue Failures → sofort fixen oder Fix reverten.**

---

## Fix-Aufgaben (aus P08a Kontext-Block)

### 1. Dokumentations-Fixes

| Finding | Fix-Methode |
|---|---|
| README veraltet | **Edit** README.md — Feature-Liste, Version, Architektur aktualisieren |
| Versions-Inkonsistenz | **Edit** alle betroffenen Dateien → gleiche Version überall |
| Veraltete TODOs | **Read** den TODO-Kontext → entweder den TODO implementieren oder den Kommentar entfernen |
| Veraltete FIXMEs | **Read** ob Bug noch existiert → wenn ja: fixen. Wenn nein: FIXME entfernen |
| Fehlende Docstrings | **Edit** Core-Module → knappe, aussagekräftige Docstrings hinzufügen |

**Docstring-Stil** (knapp, MCU-Jarvis-Projekt):
```python
async def process(self, user_input: str, user_id: str) -> str:
    """Process user input through LLM pipeline, return Jarvis response."""
```
Kein Roman — ein Satz reicht. Nur für öffentliche Core-Funktionen.

### 2. Dependency-Fixes

| Finding | Fix-Methode |
|---|---|
| Unpinned Dependencies | **Edit** requirements.txt → Version hinzufügen (`requests` → `requests>=2.31.0`) |
| Unused Dependencies | **Edit** requirements.txt → Zeile entfernen (nach Double-Check per Grep) |
| Missing Dependencies | **Edit** requirements.txt → Fehlende Dependency hinzufügen |
| Version-Konflikte | **Edit** requirements.txt → konsistente Versionen |
| Python-Version-Inkonsistenz | **Edit** Dockerfiles → gleiche Python-Version |

**Vor dem Entfernen einer Dependency:**
```
Grep: pattern="import paketname|from paketname" path="." output_mode="content"
```
→ Nur entfernen wenn **null** Treffer.

### 3. CI/CD-Fixes

| Finding | Fix-Methode |
|---|---|
| Keine GitHub Actions | **Write** `.github/workflows/ci.yml` (Template aus P08a) |
| Kein Pre-commit | **Write** `.pre-commit-config.yaml` mit ruff + basic checks |
| Fehlende Test-Automation | In CI-Workflow einbauen |

### 4. Shell-Script-Fixes

| Finding | Fix-Methode |
|---|---|
| Fehlendes Shebang | **Edit** → `#!/bin/bash` als erste Zeile |
| Fehlendes error handling | **Edit** → `set -euo pipefail` nach Shebang |
| Veraltete Pfade | **Edit** → Pfade korrigieren |
| Hardcoded Credentials | **Edit** → Environment-Variable nutzen |

### 5. Lokalisierungs-Fixes

| Finding | Fix-Methode |
|---|---|
| Fehlende Keys in de.json/en.json | **Edit** → Keys hinzufügen |
| Hardcoded Strings im Code | **Edit** → i18n-Referenz nutzen (wenn i18n-System existiert) |

---

## Fix-Strategie bei unklarem Kontext

Wenn du nicht sicher bist was der richtige Fix ist:

1. **Mehr Code lesen:**
```
Read: [betroffene Datei] offset=[relevante Zeile - 20] limit=50
Grep: pattern="[relevante Funktion]" path="." output_mode="content"
```

2. **Abhängigkeiten verstehen:**
```
Grep: pattern="import.*[betroffenes_modul]|from.*[betroffenes_modul]" path="." output_mode="content"
```

3. **Entscheidung treffen:**
- Wähle den **einfachsten Fix** der das Problem löst
- Dokumentiere WARUM du dich so entschieden hast
- Mach weiter — nicht endlos analysieren

---

## Claude Code Tool-Einsatz

| Aufgabe | Tool |
|---|---|
| Code lesen | **Read** |
| Code ändern | **Edit** |
| Neue Dateien erstellen | **Write** |
| Abhängigkeiten suchen | **Grep** |
| Tests laufen lassen | **Bash** |
| Dateien finden | **Glob** |

---

## Erfolgskriterien

- □ Alle Dokumentations-Findings aus P08a gefixt
- □ Alle Dependency-Findings aus P08a gefixt
- □ CI/CD erstellt oder verbessert
- □ Shell-Scripts gehärtet
- □ Lokalisierung vervollständigt
- □ Regression-Check: Tests bestehen weiterhin
- □ Kein Finding offen ohne dokumentierten GRUND

```
Checkliste:
□ README aktualisiert
□ Versions-Nummern synchronisiert
□ TODOs/FIXMEs aufgeräumt
□ Dependencies gepinnt/bereinigt
□ CI/CD Pipeline erstellt
□ Shell-Scripts gehärtet
□ Übersetzungen komplett
□ Tests bestehen (Regression-Check)
```

---

## Ergebnis speichern (Pflicht!)

> **Speichere dein vollständiges Ergebnis** (den gesamten Output dieses Prompts) in:
> ```
> Write: docs/audit-results/RESULT_09a_FIX_CODEQUALITAET.md
> ```
> Dies ermöglicht nachfolgenden Prompts den automatischen Zugriff auf deine Analyse.

---

## Output

Am Ende erstelle folgenden Block:

```
=== KONTEXT FUER NAECHSTEN PROMPT ===
THEMA: Code-Qualität Fixes

GEFIXT:
- [Datei:Zeile] Beschreibung des Fixes
- ...

OFFEN (mit Begründung):
- 🔴/🟠/🟡 [SEVERITY] Beschreibung | Datei:Zeile | GRUND: [warum nicht fixbar]
  → ESKALATION: NAECHSTER_PROMPT | ARCHITEKTUR_NOETIG | MENSCH

REGRESSION-CHECK:
- Baseline: [X passed, Y failed]
- Nach Fixes: [X passed, Y failed]
- Neue Failures: [KEINE / Liste]

GEAENDERTE DATEIEN: [Liste aller editierten Dateien]
===================================
```
