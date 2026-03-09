# Prompt 6: Harmonisierung — Aus 155 Modulen EIN System machen

## Rolle

Du bist ein Elite-Software-Architekt, KI-Ingenieur und MCU-Jarvis-Experte. Du hast in den vorherigen 5 Prompts das System analysiert. Jetzt baust du es zusammen.

---

## Kontext aus vorherigen Prompts

> **Wenn du Prompts 1–5 bereits in dieser Konversation bearbeitet hast**: Nutze deine eigenen Ergebnisse (Kontext-Blöcke) automatisch. Du musst nichts einfügen.
>
> **Wenn dies eine neue Konversation ist**: Füge hier die Kontext-Blöcke aus allen 5 vorherigen Prompts ein:
> - Prompt 1: Konflikt-Karte & Architektur-Bewertung (inkl. 3-Service-Architektur & Addon-Konflikte!)
> - Prompt 2: Memory-Diagnose & Root Cause (inkl. alle 12 Memory-Module)
> - Prompt 3: Flow-Analyse mit Bruchstellen & Kollisionen (inkl. Speech, Addon, Domain-Assistenten)
> - Prompt 4: Bug-Report mit allen Bugs (inkl. Security, Resilience, Addon)
> - Prompt 5: Persönlichkeits-Audit & Config-Analyse (inkl. Addon-Config)

---

## Aufgabe

Basierend auf **allen** bisherigen Erkenntnissen: Implementiere die nötigen Fixes und Refactorings, um Jarvis von einem Flickenteppich zu einem **kohärenten System** zu machen.

### Die 7 Harmonisierungs-Prinzipien

Jede Änderung muss mindestens eines dieser Prinzipien bedienen:

#### 1. Eine Stimme
Jarvis hat **eine** konsistente Persönlichkeit — egal ob normale Antwort, proaktive Warnung, Morgen-Briefing oder Fehler-Meldung.

**Was zu tun ist:**
- Alle Antwort-Pfade durch **dieselbe** Persönlichkeits-Pipeline leiten
- Keine eigenen Templates in `routine_engine.py` oder `proactive.py` die den Jarvis-Ton umgehen
- System-Prompt optimieren: Klar, fokussiert, MCU-authentisch, token-effizient

#### 2. Ein Gedächtnis
Alle Memory-Quellen fließen in **einen kohärenten Kontext** für das LLM.

**Was zu tun ist:**
- Memory-Flow reparieren oder durch robustere Alternative ersetzen (basierend auf Prompt 2)
- Sicherstellen: Conversation History + Langzeit-Fakten + gelerntes Verhalten → **ein** Kontext-Block im Prompt
- Keine isolierten Memory-Silos mehr

#### 3. Eine Entscheidungsinstanz
Wenn Module gleichzeitig handeln wollen, gibt es eine **klare Hierarchie**.

**Was zu tun ist:**
- Priority-System implementieren (oder bestehende Konflikte auflösen)
- Regel: User-Aktion > Routine > Proaktiv > Autonom
- Zentrale Queue wenn nötig, oder mindestens Mutex/Lock für kritische Aktionen

#### 4. Ein Flow
Klarer, nachvollziehbarer Datenfluss von Input bis Output.

**Was zu tun ist:**
- Bruchstellen aus Prompt 3 reparieren
- Alle kritischen Bugs aus Prompt 4 fixen (Priorität: 🔴 KRITISCH → 🟠 HOCH → 🟡 MITTEL)
- Dead Code entfernen, fehlende Verbindungen herstellen

#### 5. Ein Charakter
Gleicher Jarvis ob Frage, proaktive Warnung oder Morgen-Briefing.

**Was zu tun ist:**
- Persönlichkeits-Inkonsistenzen aus Prompt 5 beheben
- Config-Fehler aus Prompt 5 fixen
- Easter Eggs und Opinions korrekt integrieren

#### 6. Ein robustes System (NEU)
Jarvis darf **nie einfach crashen**. MCU-Jarvis funktioniert auch unter Stress.

**Was zu tun ist:**
- Security-Bugs aus Prompt 4 fixen (Prompt Injection, unvalidierte Inputs)
- Resilience-Lücken aus Prompt 4 schließen (Service-Ausfälle abfangen)
- Circuit Breaker korrekt integrieren
- Graceful Degradation wenn ein Service ausfällt

#### 7. Addon-Koordination (NEU — KRITISCH)
Assistant und Addon müssen als **ein System** agieren, nicht als zwei.

**Was zu tun ist:**
- Addon-Konflikte aus Prompt 1 (Konflikt F) auflösen
- Klare Zuständigkeiten: Wer steuert was?
- Doppelte Funktionalität eliminieren oder koordinieren
- Gemeinsamer State wenn nötig

---

## Implementierungs-Reihenfolge

Arbeite in dieser Reihenfolge — jeder Schritt baut auf dem vorherigen auf:

### Schritt 1: Kritische Bugs fixen (🔴 aus Prompt 4)
Alles was crasht oder Kern-Funktionen blockiert. **Zuerst stabilisieren.**

### Schritt 2: Memory reparieren (aus Prompt 2)
Den empfohlenen Fix oder die Alternative implementieren. **Jarvis muss sich erinnern können.**

### Schritt 3: Modul-Konflikte auflösen (aus Prompt 1)
Die gefundenen Konflikte mit klarer Hierarchie lösen. **Ein System statt 89 Inseln.**

### Schritt 4: Flows reparieren (aus Prompt 3)
Bruchstellen fixen, Kollisionen auflösen. **Jeder Pfad muss end-to-end funktionieren.**

### Schritt 5: Hohe Bugs fixen (🟠 aus Prompt 4)
Features die kaputt sind aber nicht crashen. **Features sollen wie dokumentiert funktionieren.**

### Schritt 6: Persönlichkeit harmonisieren (aus Prompt 5)
System-Prompt verbessern, Ton vereinheitlichen. **Jarvis soll wie Jarvis klingen.**

### Schritt 7: Config aufräumen (aus Prompt 5)
Unbenutzte Werte entfernen, fehlende hinzufügen. **Clean Config.**

### Schritt 8: Addon-Koordination fixen (aus Prompt 1, Konflikt F)
Assistant und Addon müssen koordiniert arbeiten. **Keine Doppelsteuerung.**

### Schritt 9: Security-Bugs fixen (aus Prompt 4)
Prompt Injection, unvalidierte Inputs, fehlende Auth. **Sicherheit.**

### Schritt 10: Resilience implementieren (aus Prompt 4)
Graceful Degradation bei Service-Ausfällen. **Jarvis darf nie einfach sterben.**

### Schritt 11: Mittlere Bugs fixen (🟡 aus Prompt 4)
Logik-Fehler und fehlende Integrationen. **Feinschliff.**

---

## Architektur-Entscheidungen

Für die Konflikte aus Prompt 1 — triff eine **klare Architektur-Entscheidung**:

### brain.py als God-Object?

Wenn Prompt 1 ergeben hat, dass brain.py zu viel macht:
- **Option A**: Bestehendes brain.py refactoren — klare Zuständigkeiten, keine God-Object-Methoden
- **Option B**: Event-Bus einführen — Module kommunizieren über Events statt direkte Aufrufe
- **Option C**: Pipeline-Pattern — Klarer Datenfluss Input → Processing → Output
- **Option D**: Mediator-Pattern — brain.py als schlanker Vermittler, Logik in Modulen

Wähle die Option die mit **minimalem Umbau den größten Effekt** hat. Over-Engineering vermeiden.

### Memory-Architektur

Basierend auf Prompt 2 — implementiere die empfohlene Lösung:
- Wenn das 3-Tier-System reparierbar ist: Repariere es
- Wenn eine einfachere Alternative robuster ist: Implementiere sie
- **Ziel**: Jarvis merkt sich Gespräche, Fakten und Vorlieben — zuverlässig

---

## Output-Format

### 1. Änderungs-Log

**Claude Code: Nutze das Edit-Tool um Änderungen DIREKT in den Dateien zu machen.** Zeige nicht nur Diffs — schreibe die Fixes direkt in den Code.

Für jede Änderung:
```
### [Schritt X] Datei: path/to/file.py
**Prinzip**: [Eine Stimme / Ein Gedächtnis / ...]
**Bug-Ref**: #X aus Prompt 4 (falls Bug-Fix)
**Was geändert**: Kurzbeschreibung
**Warum**: Begründung
→ Edit-Tool: Änderung direkt in der Datei durchgeführt
```

### 2. Architektur-Entscheidungen

| Entscheidung | Gewählte Option | Begründung |
|---|---|---|
| brain.py Refactoring | ? | ? |
| Memory-Architektur | ? | ? |
| Priority-System | ? | ? |

### 3. Verifikation

Nach allen Änderungen — prüfe:
- [ ] Jarvis startet ohne Fehler
- [ ] Sprach-Input → Antwort funktioniert end-to-end
- [ ] Jarvis erinnert sich an das letzte Gespräch
- [ ] Proaktive Warnungen werden korrekt zugestellt
- [ ] Morgen-Briefing läuft durch
- [ ] Der Ton ist konsistent über alle Pfade
- [ ] Keine neuen Bugs eingeführt

### 4. Offene Punkte

Was konnte in diesem Durchlauf **nicht** gelöst werden und braucht einen weiteren Prompt/Session?

> **WICHTIG**: Nach Prompt 6 kommt **Prompt 7: Testing & Deployment**. Dort werden alle Fixes verifiziert, Tests ausgeführt und das Deployment geprüft.

---

## Regeln

### Gründlichkeits-Pflicht

> **Jeder Fix muss VERIFIZIERT sein.** Lies die Datei mit Read, mache die Änderung mit Edit, lies den umgebenden Code, stelle sicher dass der Fix keine neuen Probleme einführt. Prüfe mit Grep alle Aufrufer der geänderten Funktion.

### Claude Code Tool-Einsatz in diesem Prompt

| Aufgabe | Tool | Wichtig |
|---|---|---|
| Datei lesen vor dem Fix | **Read** | IMMER erst lesen, dann editieren |
| Fix implementieren | **Edit** | Direkt in der Datei ändern — KEIN "hier ist der Diff" |
| Aufrufer prüfen nach Fix | **Grep** | `pattern="geänderte_funktion" path="assistant/"` |
| Tests nach Fix laufen lassen | **Bash** | `cd assistant && python -m pytest tests/test_betroffenes_modul.py -x` |
| Commit nach Fix-Gruppe | **Bash** | `git add -p && git commit -m "Fix: Beschreibung"` |

**Workflow pro Fix:**
1. **Read** — Datei lesen, Problem verifizieren
2. **Grep** — Alle Aufrufer/Abhängigkeiten finden
3. **Edit** — Fix direkt schreiben
4. **Grep** — Prüfen ob der Fix konsistent ist mit allen Aufrufern
5. **Bash** — Betroffene Tests laufen lassen
6. Nächster Fix

- **Einfach > Komplex** — Wenn ein simpler Fix reicht, kein Refactoring nötig
- **Nicht alles auf einmal** — Lieber 10 solide Fixes als 30 hastige
- **Reihenfolge einhalten** — Stabilität vor Features vor Feinschliff
- **Jede Änderung committen** — Klare, beschreibende Commit Messages mit `git commit`
- **MCU-Jarvis als Maßstab** — Bei jeder Entscheidung: "Würde der echte Jarvis das so machen?"
- **Keine neuen Module** ohne guten Grund — Bestehende Module verbessern statt neue hinzufügen
- **Tests nicht brechen** — Nach jedem Fix mit Bash `pytest` ausführen

---

## ⚡ Übergabe an Prompt 7

Formatiere am Ende deiner Arbeit einen kompakten **Kontext-Block** für Prompt 7:

```
## KONTEXT AUS PROMPT 6: Harmonisierung

### Änderungs-Log
[Schritt → Datei → Was geändert → Warum — kompakt]

### Architektur-Entscheidungen
[brain.py → Entscheidung, Memory → Entscheidung, Priority-System → Entscheidung]

### Behobene Bugs
[Liste: Bug-# aus Prompt 4 → Status (gefixt/verschoben/offen)]

### Verifikations-Checkliste
[Welche Checks bestanden, welche nicht]

### Offene Punkte
[Was in Prompt 7 verifiziert/getestet werden muss]
```

**Wenn du Prompt 7 in derselben Konversation erhältst**: Setze alle bisherigen Kontext-Blöcke (Prompt 1–6) automatisch ein.
