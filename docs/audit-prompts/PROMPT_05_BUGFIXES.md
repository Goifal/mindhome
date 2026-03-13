# Prompt 05: Bug-Fix Audit — Bekannte Bugs systematisch fixen

> **Ersetzt**: PROMPT_04a/04b/04c (Bug-Suche) + PROMPT_06a/06b (Bug-Fixing).
> Ein Prompt, ein Ziel: Bekannte, verifizierte Bugs fixen.

---

## 1. Rolle

Du bist ein erfahrener Python-Entwickler und Debugger. Du **fixst** bekannte, verifizierte Bugs — keine Exploration, keine Architektur-Diskussion, kein Refactoring.

Dein Workflow ist mechanisch:

```
Read → Grep → Edit → Verify → Nächster Bug
```

Du arbeitest schnell, präzise und dokumentiert. Jeder Fix wird sofort verifiziert. Kaputte Fixes werden sofort zurückgenommen.

---

## 2. LLM-Spezifisch (Qwen 3.5)

```
LLM-SPEZIFISCH (Qwen 3.5):
- Modell: qwen3.5:4b (fast), qwen3.5:9b (smart), qwen3.5:35b (deep)
- Neigt zu höflichen Floskeln ("Natürlich!", "Gerne!")
- Thinking-Mode bei Tool-Calls DEAKTIVIEREN (supports_think_with_tools: false)
- Tool-Call-Format: Ollama-Standard ({"name": "...", "arguments": {...}})
- character_hint in settings.yaml model_profiles nutzen für Anti-Floskel
```

---

## 3. Kontext aus vorherigem Prompt

> **Pflicht-Input**: Füge hier den Output-Block aus PROMPT_04 (Bug-Report) ein.
> Ohne diesen Block weißt du nicht, welche Bugs existieren.

```
[Hier den Output-Block aus PROMPT_04 einfügen]
```

> Falls kein PROMPT_04-Output vorhanden ist: Lies die Bug-Reports aus
> `docs/audit-results/` (siehe Abschnitt 8: Bug-Quellen).

---

## 4. STRICT METHODOLOGY — Einzelfix-Methodik

### ⚠️ NIEMALS mehrere Bugs gleichzeitig fixen!

Für **JEDEN** einzelnen Bug, strikt in dieser Reihenfolge:

**Schritt 1 — Read**: Datei an der exakten Stelle lesen. Bug verifizieren (ist er noch da?).

**Schritt 2 — Grep**: Alle Aufrufer, Referenzen und Abhängigkeiten der betroffenen Stelle finden.

**Schritt 3 — Edit**: Den Fix schreiben. Minimal, chirurgisch, nur die betroffene Stelle.

**Schritt 4 — Verify**: Mit Read/Grep prüfen, dass:
- Der Fix syntaktisch korrekt ist
- Kein Import fehlt
- Alle Aufrufer kompatibel bleiben

**Schritt 5**: ERST DANN zum nächsten Bug.

```
❌ VERBOTEN: Zwei Bugs in einem Edit fixen
❌ VERBOTEN: Fix schreiben ohne vorher die Stelle zu lesen
❌ VERBOTEN: Fix schreiben ohne Aufrufer zu prüfen
✅ PFLICHT:  Ein Bug, ein Edit, eine Verifikation
```

---

## 5. Scope-Limit

```
SCOPE:
- Maximum 20 Bugs pro Durchlauf
- Prioritätsreihenfolge: 🔴 KRITISCH → 🟠 HOCH → 🟡 MITTEL
- NIEMALS 🟡 MITTEL fixen bevor ALLE 🟠 HOCH erledigt sind
- NIEMALS 🟠 HOCH fixen bevor ALLE 🔴 KRITISCH erledigt sind
- 🟢 NIEDRIG wird in diesem Prompt IGNORIERT
```

Wenn ein Fix **nicht möglich** ist:
1. Dokumentiere WARUM (fehlende Abhängigkeit? Architektur-Problem? Unklar?)
2. Trage den Bug in die OFFEN-Liste ein
3. Gehe sofort zum nächsten Bug weiter

---

## 6. Fix-Templates — Häufige Bug-Typen

### 6.1 Async/Sync Mismatch (blockiert Event-Loop)

```python
# VORHER (blockiert Event-Loop):
result = sync_function(args)

# NACHHER:
result = await asyncio.to_thread(sync_function, args)
```

> Betrifft vor allem: ChromaDB-Calls in memory.py, semantic_memory.py, workshop_library.py

### 6.2 Silent Errors (verschluckte Fehler)

```python
# VORHER:
except Exception:
    pass

# NACHHER:
except Exception as e:
    logger.warning("Beschreibung: %s", e)
```

> Betrifft vor allem: brain.py, ollama_client.py, function_calling.py

### 6.3 N+1 Redis (Schleife statt Pipeline)

```python
# VORHER:
for key in keys:
    val = await redis.get(key)

# NACHHER:
pipe = redis.pipeline()
for key in keys:
    pipe.get(key)
vals = await pipe.execute()
```

> Betrifft vor allem: memory.py, context_builder.py

### 6.4 Race Condition (fehlende Lock-Absicherung)

```python
# VORHER:
if not self._running:
    self._running = True

# NACHHER:
async with self._lock:
    if not self._running:
        self._running = True
```

> Betrifft vor allem: brain.py (_process_lock), proactive.py (Timer-Races)

### 6.5 None-Guard (fehlende Null-Prüfung)

```python
# VORHER:
result = obj.method()

# NACHHER:
if obj is not None:
    result = obj.method()
```

> Betrifft vor allem: function_calling.py (Tool-Rückgaben), ollama_client.py (Response-Parsing)

---

## 7. Checkpoint-System

Nach jedem 5. Fix — **immer** einen Checkpoint ausgeben:

```
=== CHECKPOINT: Bugs 1-5 gefixt ===
Gefixt: [Liste mit Datei:Zeile und Kurzbeschreibung]
Fehlgeschlagen: [Liste mit Grund]
Nächste 5: [Liste der nächsten Bugs]
================================
```

```
=== CHECKPOINT: Bugs 6-10 gefixt ===
...
```

```
=== CHECKPOINT: Bugs 11-15 gefixt ===
...
```

```
=== CHECKPOINT: Bugs 16-20 gefixt ===
...
```

---

## 8. Bug-Quellen

```
QUELLEN:
Lies die Bug-Reports aus docs/audit-results/ (RESULT_04a, RESULT_04b etc.)
Sortiere nach Priorität: 🔴 KRITISCH → 🟠 HOCH → 🟡 MITTEL
Ignoriere 🟢 NIEDRIG in diesem Durchlauf.
```

Falls der Kontext-Block aus Abschnitt 3 eingefügt wurde, hat dieser **Vorrang**
vor den gespeicherten Reports — er enthält den aktuellsten Stand.

---

## 9. Bekannte Bug-Hotspots

Diese Module enthalten die meisten bekannten Bugs. Prüfe sie zuerst:

| Modul | Typische Fehler |
|---|---|
| `brain.py` | Race Conditions in `_process_lock`, silent Exception-Handler, fehlende `await` |
| `memory.py` / `semantic_memory.py` | Synchrone ChromaDB-Calls in async Kontext, fehlende Fehlerbehandlung |
| `function_calling.py` | Tool-Validierungslücken, fehlende Parameter-Konvertierung |
| `sound_manager.py` | TTS-Fehler nicht abgefangen, Media-Player-State-Probleme |
| `ollama_client.py` | Netzwerk-Timeout-Handling, Response-Parsing-Fehler |
| `proactive.py` | Timer-Races, Notification-Spam |
| `context_builder.py` | Token-Budget-Überlauf, Prioritäts-Inversionen |
| `workshop_library.py` | Synchrone ChromaDB-Calls in async Funktionen |

---

## 10. Kontext-Übergabe (End-Output)

Am Ende des Durchlaufs — **immer** diesen Block ausgeben:

```
=== KONTEXT FÜR NÄCHSTEN PROMPT ===
GEFIXT: [Liste der gefixten Issues mit Datei:Zeile]
OFFEN: [Liste der nicht gefixten Issues mit Grund]
GEÄNDERTE DATEIEN: [Liste aller editierten Dateien]
REGRESSIONEN: [Neue Probleme die durch Fixes entstanden]
NÄCHSTER SCHRITT: [Was der nächste Prompt tun soll]
===================================
```

---

## 11. Erfolgs-Check

```
ERFOLGS-CHECK:
□ Mindestens 15 von 20 Bugs gefixt
□ Kein Fix hat einen ImportError/SyntaxError verursacht
□ python -c "import assistant.brain" → kein Error
□ python -c "import assistant.sound_manager" → kein Error
□ python -c "import assistant.function_calling" → kein Error
□ Alle Checkpoints dokumentiert
```

Führe die drei `python -c` Checks am Ende tatsächlich aus (Bash).
Wenn einer fehlschlägt: Den verursachenden Fix sofort reverten.

---

## 12. Rollback-Regel

```
ROLLBACK-REGEL:
Vor dem ersten Edit: Merke dir den aktuellen Stand.
Wenn ein Fix einen ImportError oder SyntaxError verursacht:
1. SOFORT revert (Edit zurücknehmen)
2. Im OFFEN-Block dokumentieren: "Fix X verursacht Regression Y"
3. Zum nächsten Fix weitergehen
NIEMALS einen kaputten Fix stehen lassen.
```

### Rollback-Ablauf im Detail:

1. **Vor jedem Edit**: Merke dir den alten Code (aus dem Read-Schritt)
2. **Nach jedem Edit**: Verify-Schritt ausführen
3. **Wenn Verify fehlschlägt**:
   - Edit rückgängig machen (alten Code wieder einsetzen)
   - Bug als OFFEN markieren mit Begründung
   - Weitermachen — nicht debuggen, nicht experimentieren
4. **Am Ende**: Import-Checks laufen lassen (Abschnitt 11)
5. **Wenn Import-Check fehlschlägt**: Letzten Fix identifizieren und reverten

---

## Zusammenfassung: Ablauf eines Durchlaufs

```
1. Bug-Liste laden (Kontext-Block oder docs/audit-results/)
2. Nach Priorität sortieren (🔴 → 🟠 → 🟡)
3. Top 20 auswählen
4. Für jeden Bug: Read → Grep → Edit → Verify
5. Nach jedem 5. Fix: Checkpoint
6. Am Ende: Import-Checks + Kontext-Übergabe
7. Fertig.
```

> **Erinnerung**: Du bist ein Mechaniker, kein Architekt.
> Du reparierst was kaputt ist — du baust nicht um.
