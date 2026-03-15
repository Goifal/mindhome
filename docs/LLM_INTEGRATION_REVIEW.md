# LLM Integration Review — Realistische Verbesserungen fuer Maximum JARVIS

**Datum:** 2026-03-15
**Basis:** Deep-Dive-Analyse des gesamten Codebases + Qwen3.5 Capabilities
**Fokus:** Nur Dinge die SINN machen und den groessten Unterschied bringen

---

## Status Quo: Was bereits gut funktioniert

| Feature | Status | Wo |
|---|---|---|
| Native Tool Calling | Funktioniert | ollama_client.py, function_calling.py |
| Think-Tag-Steuerung | auto/on/off | brain.py:3325-3340, ollama_client.py |
| Model-Cascade | Fast→Smart→Deep Fallback | brain.py:885 `_llm_with_cascade()` |
| Streaming | Mit Think-Tag-Filter | ollama_client.py `stream_chat()` |
| Model-Profile | Per-Modell top_p/top_k/repeat_penalty | config.py:82-99, settings.yaml |
| Prompt-Injection-Schutz | F-001 bis F-084 | context_builder.py |
| Context-Building | 16+ Kategorien parallel | context_builder.py:216 asyncio.gather |
| Correction Memory | LLM lernt aus Fehlern | correction_memory.py → brain.py:2861 |

---

## Verbesserung 1: Context Window vergroessern (SOFORT, 5 Min, RIESIGER Impact)

### Problem

```yaml
# Aktuell in settings.yaml:
ollama:
  num_ctx_fast: 2048    # 0.8% von 262K
  num_ctx_smart: 4096   # 1.6% von 262K
  num_ctx_deep: 8192    # 3.1% von 262K
```

Qwen3.5-35B-A3B hat 262.144 Tokens Context Window. Ihr nutzt davon fast nichts.
Das bedeutet: JARVIS vergisst Gespraeche nach wenigen Turns, hat kaum Platz fuer
Kontext-Daten, und kann keine langen Zusammenhaenge erkennen.

### Loesung

```yaml
ollama:
  num_ctx_fast: 8192     # Genug fuer einfache Befehle + kurze Historie
  num_ctx_smart: 32768   # Guter Kompromiss: ~20 Turns + voller Kontext
  num_ctx_deep: 65536    # Komplexe Analysen mit langer Historie
```

### Warum das sicher ist

- Qwen3.5-35B-A3B ist MoE mit nur 3B aktiven Parametern → VRAM-Verbrauch steigt
  moderat (KV-Cache waechst, aber kein Modell-Reload)
- Auf 24GB VRAM: 32K Context ist komfortabel machbar, 65K moeglicherweise
  (testen mit `ollama run qwen3.5:35b /set parameter num_ctx 32768`)
- Falls VRAM knapp: 16K/32K statt 32K/65K — immer noch 4-8x besser als jetzt

### Impact

- JARVIS erinnert sich an 20+ Turns statt 3-5
- Mehr Raum fuer Kontext-Daten (Haus-Status, Memory, Kalender)
- Persoenlichkeit bleibt konsistenter ueber lange Gespraeche
- **Geschaetzter JARVIS-Uplift: +8-12%**

---

## Verbesserung 2: Daten-Inseln ans LLM anbinden (1-2h, hoher Impact)

### Problem: 3 Module rechnen im Dunkeln

Das LLM sieht NICHT:
1. **Energiedaten** (energy_optimizer.py) — Kosten, Solar-Produktion, Anomalien
2. **Gaeste-Status** (visitor_manager.py) — Wer ist da, wie lange schon
3. **Audio-Kontext** (ambient_audio.py) — Was ist gerade hoerbar

### Loesung: Context-Builder erweitern

**Energie-Kontext** in context_builder.py:
```python
# In build() bei den bestehenden asyncio.gather Tasks:
energy_ctx = await self.energy_optimizer.get_context_summary()
# Ergebnis z.B.: "Solar: 4.2kW Produktion, Verbrauch: 1.8kW, Batterie: 87%"
# → JARVIS kann sagen: "Guter Zeitpunkt fuer die Waschmaschine, Sir."
```

**Gaeste-Kontext** in context_builder.py ODER personality.py:
```python
visitor_status = await self.visitor_manager.get_active_visitors()
# Ergebnis z.B.: "Gaeste anwesend: 2 Personen seit 14:30"
# → personality.py: Formeller Ton, keine Inside Jokes, keine privaten Infos
```

**Audio-Kontext** in context_builder.py:
```python
audio_ctx = await self.ambient_audio.get_recent_classifications()
# Ergebnis z.B.: "Musik laeuft im Wohnzimmer, TV an in Schlafzimmer"
# → JARVIS versteht den Kontext: "Soll ich die Musik leiser machen?"
```

### Warum realistisch

- Die Module existieren BEREITS und haben Daten
- Nur get_*() Methoden noetig die einen kurzen String zurueckgeben
- In context_builder.py zum bestehenden asyncio.gather hinzufuegen
- Hinter Feature-Toggle in settings.yaml
- Kein Architektur-Umbau noetig

### Impact

- JARVIS reagiert auf Energie-Situationen proaktiv
- JARVIS passt sich an Gaeste an (der MCU-JARVIS-Moment: andere Leute im Raum)
- JARVIS versteht die akustische Situation
- **Geschaetzter JARVIS-Uplift: +5-8%**

---

## Verbesserung 3: Multi-Turn Tool Calling (2-3h, hoher Impact)

### Problem

Aktuell: LLM ruft Tool auf → bekommt Ergebnis → antwortet dem User.
Es kann NICHT: Ergebnis analysieren → naechsten Tool-Call entscheiden → iterieren.

Beispiel was NICHT geht:
```
User: "Mach das Haus bereit fuer den Abend"
JARVIS denkt: get_lights → sieht welche an sind → set_light dimmen
             → get_climate → Temperatur checken → set_climate anpassen
             → get_covers → Rollladen Status → set_cover schliessen
```
Stattdessen: JARVIS muss ALLES in einem Schritt planen, ohne Zwischenergebnisse.

### Loesung: Tool-Loop in brain.py

```python
# In _process_inner() nach dem ersten LLM-Call:
MAX_TOOL_ITERATIONS = 3  # Sicherheitsgrenze

for iteration in range(MAX_TOOL_ITERATIONS):
    response = await self._llm_call(messages, tools=tools)

    if not response.tool_calls:
        break  # LLM ist fertig, hat finale Antwort

    # Tool-Calls ausfuehren
    tool_results = await self._execute_tool_calls(response.tool_calls)

    # Ergebnisse zurueck ins Gespraech
    messages.append({"role": "assistant", "content": "", "tool_calls": response.tool_calls})
    for result in tool_results:
        messages.append({"role": "tool", "content": result})

    # Naechste Iteration: LLM sieht Ergebnisse und entscheidet weiter
```

### Warum realistisch

- Ollama unterstuetzt das nativ (Messages mit role: tool)
- Qwen3.5 ist auf Tool-Calling trainiert und kann iterieren
- Safety: MAX_ITERATIONS + Timeout verhindern Endlosschleifen
- action_planner.py existiert bereits fuer Multi-Step — dieser Ansatz ist einfacher

### Impact

- "Mach das Haus bereit" funktioniert in einem Gespraech statt 3 separaten
- JARVIS kann auf Tool-Ergebnisse reagieren ("Licht war schon aus, ueberspringe ich")
- Komplexe Aufgaben werden moeglich
- **Geschaetzter JARVIS-Uplift: +5-7%**

---

## Verbesserung 4: Task-aware Temperature (30 Min, mittlerer Impact)

### Problem

Temperature ist hardcoded pro Aufruf-Kontext in brain.py:
- 0.7 Standard, 0.4 Feedback, 0.1 Fakten, 0.3 Retry, 0.5 Narrativ
- ABER: "Licht an" und "Erzaehl mir was" bekommen beide 0.7

### Loesung: In model_router.py

```python
TASK_TEMPERATURES = {
    "device_control": 0.3,   # Praezise: "Licht an" braucht keine Kreativitaet
    "device_query": 0.4,     # Leicht kreativ: "Wie warm ist es?" → nette Formulierung
    "conversation": 0.75,    # Natuerlich: Plaudern, Meinungen, Humor
    "analysis": 0.5,         # Balanced: "Warum ist es kalt?"
    "creative": 0.85,        # Kreativ: Geschichten, Witze, Ideen
    "safety": 0.15,          # Ultra-praezise: Alarme, Warnungen
}

def route(self, text, ...):
    tier, task_type = self._classify(text)
    temperature = TASK_TEMPERATURES.get(task_type, 0.7)
    return tier, temperature
```

### Warum realistisch

- model_router.py hat bereits Keyword-Matching fuer Tier-Auswahl
- Task-Typ-Erkennung ist eine einfache Erweiterung des bestehenden Codes
- Keine Architektur-Aenderung, nur ein Dict + Return-Wert-Erweiterung
- brain.py muss die Temperature nur durchreichen statt hardcoden

### Impact

- "Licht an" → praezise, kein Gefasel
- "Wie war dein Tag?" → kreativ, humorvoll, menschlich
- Alarme → sofort, klar, kein Humor
- **Geschaetzter JARVIS-Uplift: +3-5%**

---

## Verbesserung 5: Visitor-Status → Personality-Anpassung (1h, mittlerer Impact)

### Problem

visitor_manager.py erkennt Gaeste, aber JARVIS aendert sein Verhalten NULL.
MCU JARVIS ist bei Gaesten formeller, diskreter, zeigt keine internen Ablaeufe.

### Loesung: personality.py erweitern

```python
# In build_system_prompt():
visitor_status = await self._get_visitor_status()
if visitor_status.guests_present:
    guest_section = """
GAESTE ANWESEND:
- Formeller Ton, kein Sarkasmus ueber Level 1
- Keine internen Witze oder private Informationen
- Keine Hinweise auf Routinen oder Gewohnheiten der Bewohner
- Professionell und zuvorkommend, wie ein erstklassiger Butler
"""
else:
    guest_section = ""
```

### Warum das MCU-JARVIS ist

Tony hat Gaeste → JARVIS ist professioneller Butler.
Tony ist allein → JARVIS ist Kumpel mit Sarkasmus.
Genau dieser Switch macht JARVIS lebendig.

### Impact

- **Geschaetzter JARVIS-Uplift: +2-4%**

---

## Verbesserung 6: Parallel Tool Execution (1-2h, mittlerer Impact)

### Problem

Aktuell: Tool 1 ausfuehren → warten → Tool 2 ausfuehren → warten → Tool 3...
Bei "Mach alles aus": 5 Lichter × 0.5s = 2.5s statt 0.5s parallel.

### Loesung

```python
# In function_calling.py oder brain.py:
async def _execute_tool_calls(self, tool_calls):
    # Unabhaengige Calls identifizieren
    independent = [tc for tc in tool_calls if not self._depends_on_previous(tc)]
    dependent = [tc for tc in tool_calls if self._depends_on_previous(tc)]

    # Unabhaengige parallel ausfuehren
    results = await asyncio.gather(*[
        self._execute_single_tool(tc) for tc in independent
    ])

    # Abhaengige sequentiell
    for tc in dependent:
        results.append(await self._execute_single_tool(tc))

    return results
```

### Warum realistisch

- asyncio.gather ist bereits ueberall im Code verwendet
- Die meisten Tool-Calls sind unabhaengig (3 Lichter schalten = parallel)
- Abhaengigkeits-Erkennung: Einfach = alle set_* parallel, get→set sequentiell

### Impact

- Schnellere Multi-Device-Aktionen
- JARVIS wirkt reaktionsschneller
- **Geschaetzter JARVIS-Uplift: +2-3%**

---

## Verbesserung 7: Multi-Modell-Setup nutzen (30 Min Config, hoher Impact)

### Problem

Alle 3 Tiers (Fast/Smart/Deep) zeigen auf dasselbe Modell: qwen3.5:35b.
Das Model-Routing ist dadurch sinnlos.

### Loesung: Verschiedene Qwen3.5-Varianten

```yaml
# settings.yaml:
models:
  fast: qwen3.5:4b       # 4B → blitzschnell fuer "Licht an" (~200ms)
  smart: qwen3.5:35b     # 35B-A3B MoE → Standard-Konversation
  deep: qwen3.5:27b      # 27B Dense → maximale Qualitaet fuer komplexe Fragen
```

### Warum das funktioniert

- **qwen3.5:4b** braucht ~3GB VRAM, laeuft parallel zum 35B
- **qwen3.5:35b-A3B** (3B aktiv) → schnell fuer den Alltag
- **qwen3.5:27b** (dense) → alle 27B Parameter aktiv, "smarter" bei Reasoning
- 24GB VRAM: 4B + 35B-A3B passt easy, 27B Dense muss evtl. den 35B entladen
  (Ollama macht das automatisch mit keep_alive)
- Qwen3.5-9B waere eine Alternative fuer Fast wenn 4B zu schwach ist

### Impact

- "Licht an" in ~200ms statt 1s
- Komplexe Fragen mit hoeherer Qualitaet (27B Dense > 35B-A3B bei Reasoning)
- Model-Routing wird erstmals sinnvoll
- **Geschaetzter JARVIS-Uplift: +5-8%**

---

## Verbesserung 8: Strukturierte JSON-Ausgabe fuer Tool-Calls (1h, Stabilitaet)

### Problem

Tool-Call-Argumente werden als Free-Form-Text generiert. Das fuehrt gelegentlich
zu halluzinierten Parametern oder falsch formatierten Werten.

### Loesung

Ollama unterstuetzt `format: "json"` im API-Call. Fuer Tool-Calls:

```python
# In ollama_client.py bei Tool-Calls:
if tools:
    payload["format"] = "json"  # Erzwingt valides JSON
```

ACHTUNG: Nur fuer Tool-Call-Responses, NICHT fuer normale Konversation
(dort wuerde es die natuerliche Sprache zerstoeren).

### Warum realistisch

- Ollama unterstuetzt es nativ
- Qwen3.5 ist auf strukturierte Ausgabe trainiert
- Reduziert Tool-Call-Fehler signifikant

### Impact

- Weniger fehlgeschlagene Tool-Calls
- Zuverlaessigere Geraetesteuerung
- **Geschaetzter JARVIS-Uplift: +1-2% (Stabilitaet, nicht Persoenlichkeit)**

---

## Verbesserung 9: Think-Tags breiter einsetzen (30 Min, mittlerer Impact)

### Problem

Think-Tags (`<think>`) sind NUR bei Problem-Solving und What-If aktiv (brain.py:3325-3340).
Bei Device-Commands explizit deaktiviert.

### Wo Think-Tags zusaetzlich Sinn machen

```python
# In brain.py _get_think_mode():
# BEHALTEN: off bei einfachen Device-Commands (Latenz)
# NEU AKTIVIEREN bei:
think_contexts = {
    "safety_decision": True,     # "Soll ich den Rauchmelder stumm schalten?"
    "energy_optimization": True, # "Wann Waschmaschine starten?"
    "multi_device": True,        # "Mach das Haus bereit" → Reihenfolge planen
    "conflict_resolution": True, # "Heizung an aber Fenster offen"
    "proactive_insight": True,   # Background Reasoning
}
```

### Warum realistisch

- Think-Tags-Infrastruktur existiert komplett (Steuerung, Stripping, Streaming-Filter)
- Nur die Bedingungen in `_get_think_mode()` erweitern
- Kein neuer Code noetig

### Impact

- Bessere Entscheidungen bei Sicherheits-Fragen
- Klugere Multi-Step-Planung
- **Geschaetzter JARVIS-Uplift: +2-4%**

---

## Verbesserung 10: Energie-Kontext → Proaktive Vorschlaege (1h, mittlerer Impact)

### Problem

energy_optimizer.py berechnet: Solar-Produktion, Verbrauch, Kosten-Anomalien,
guenstige Zeitfenster. Aber JARVIS weiss davon NICHTS.

### Loesung: Energie-Insights in den Prompt

```python
# In context_builder.py:
energy_summary = await self.energy_optimizer.get_brief_status()
# → "Solar: 4.2kW, Verbrauch: 1.8kW, Ueberschuss: 2.4kW, Batterie: 87%"

# In personality.py Prompt-Sektion:
# ENERGIE-BEWUSSTSEIN:
# Wenn Energiedaten im Kontext: Erwaehne guenstige Zeitfenster beilaeuifig.
# "Uebrigens, guter Zeitpunkt fuer die Waschmaschine — voller Sonnenschein."
# Nicht bei jedem Gespraech. Nur wenn relevant oder auf Nachfrage.
```

### Warum das MCU-JARVIS ist

MCU JARVIS: "Sir, die Reaktor-Leistung ist bei 400%. Soll ich auf den
Arc-Reaktor umschalten?"
Euer JARVIS: "Sir, Solar-Ueberschuss von 2.4 Kilowatt. Guter Zeitpunkt
fuer energieintensive Geraete."

### Impact

- JARVIS wirkt intelligenter und mitdenkend
- Konkrete Kosteneinsparung fuer den Haushalt
- **Geschaetzter JARVIS-Uplift: +2-3%**

---

## Zusammenfassung: Priorisierte Reihenfolge

| # | Verbesserung | Aufwand | Impact | Kumulativ |
|---|---|---|---|---|
| 1 | Context Window erhoehen | 5 Min | +8-12% | ~60-72% |
| 7 | Multi-Modell-Setup | 30 Min | +5-8% | ~65-77% |
| 2 | Daten-Inseln anbinden | 1-2h | +5-8% | ~68-80% |
| 3 | Multi-Turn Tool Calling | 2-3h | +5-7% | ~70-82% |
| 4 | Task-aware Temperature | 30 Min | +3-5% | ~72-84% |
| 9 | Think-Tags breiter | 30 Min | +2-4% | ~73-85% |
| 5 | Visitor → Personality | 1h | +2-4% | ~74-86% |
| 6 | Parallel Tool Execution | 1-2h | +2-3% | ~75-87% |
| 10 | Energie-Kontext | 1h | +2-3% | ~76-88% |
| 8 | JSON-Mode fuer Tools | 1h | +1-2% | ~76-88% |

**Realistisches Maximum mit allen 10 Verbesserungen + Masterplan Phase 1-3: ~70-80% MCU JARVIS**

### Die ehrliche Obergrenze

Die verbleibenden 20-30% sind:
- **TTS-Qualitaet** (~10-15%) — Piper vs. Paul Bettany, kein Software-Fix
- **LLM-Reasoning-Tiefe** (~5-10%) — Qwen3.5 35B ist sehr gut, aber nicht Opus/GPT-5
- **Latenz** (~3-5%) — 0.5-2s vs. Echtzeit im Film

Mit einem **TTS-Upgrade** (z.B. Fish Speech, XTTS v2, Kokoro) koennte man auf 80-88% kommen.
Das waere fuer ein lokales System auf eigener Hardware **aussergewoehnlich**.

---

## Was ich NICHT empfehle (aus dem Masterplan)

| Feature | Warum nicht |
|---|---|
| B7 Unified Consciousness | `_mega_tasks` + asyncio.gather IST bereits ein Single-Pass. Refactoring von 10K-Zeilen brain.py ist Risiko ohne Gewinn |
| D7 Prompt-Versionierung | A/B-Testing braucht statistisch signifikante Datenmengen. Bei 2 Usern nicht sinnvoll |
| D6 Dynamic Few-Shot | Gute Idee, aber erst wenn D5 (Quality Feedback) stabil laeuft. Abhaengigkeit beachten |
| B4 Background Reasoning | GPU-Contention-Risiko. Besser: Energie/Kalender-Daten PASSIV in den Kontext, statt aktiv im Idle das LLM zu beschaeftigen |
