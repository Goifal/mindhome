# Jarvis Finetuning — Schritt-für-Schritt Umbauplan

**Datum**: 2026-03-09
**Ziel**: Jarvis der sich erinnert, mitdenkt, und Charakter hat — gleichzeitig, nicht abwechselnd.
**Prinzip**: Konsolidieren vor Expandieren. Kein neues Feature bis das Fundament steht.
**Reihenfolge ist kritisch**: Phase 0 → 1 → 2 → 3. Jede Phase baut auf der vorherigen auf.

---

## Phase 0: Sofort-Fixes (Bugs die jetzt Daten vernichten)

Kein Umbau, nur gezielte Bugfixes. Kann sofort gemacht werden.

---

### Fix 0.1: `clear_all_memory()` — fehlende Keys

**Datei**: `assistant/assistant/memory.py` → Methode `clear_all_memory()` (ca. Zeile 493-507)

**Problem**: Beim Memory-Reset werden die Keys `mha:memory:projects`, `mha:memory:open_questions` und `mha:memory:summary:*` in Redis NICHT gelöscht. Das bedeutet: nach einem vollständigen Reset bleiben alte Projekte und offene Fragen als Geister-Daten im System. Der User denkt alles ist weg, aber Jarvis hat noch Überreste.

**Ursache**: `clear_all_memory()` scannt nur bestimmte Key-Prefixes (`mha:conversation:*`, `mha:emotion:*`, etc.), aber das Prefix `mha:memory:*` (genutzt von `conversation_memory.py`) fehlt komplett.

**Lösung**: In der Scan-Schleife von `clear_all_memory()` zusätzlich nach `mha:memory:*` scannen:

```python
async for key in self.redis.scan_iter(match="mha:memory:*"):
    keys.append(key)
```

**Regel**: Reset = ALLES weg. Kein Backup, keine Rückfrage, keine Ausnahmen. Wenn der User "Lösche mein Gedächtnis" sagt, meint er es. Alle `mha:*` Keys müssen gelöscht werden — Projekte, offene Fragen, Summaries, alles.

**Aufwand**: 3 Zeilen Code.

---
