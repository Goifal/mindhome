# Changelog

## 0.7.18 – Stale-Pattern-Cleanup + defaultdict-Fix

### Fix
- **defaultdict-Import**: "cannot access local variable 'defaultdict'" — doppelter Import entfernt (war schon global importiert)
- **Stale-Pattern-Cleanup**: Nach jeder Analyse werden Patterns automatisch geloescht, die in diesem Lauf nicht bestaetigt/aktualisiert wurden. Betrifft nur `status=observed` — vom User bestaetigte/abgelehnte Patterns bleiben erhalten. Loest das Problem: 4.234 alte Korrelationen blieben in der DB obwohl die neuen Filter sie nicht mehr erzeugen

## 0.7.17 – Korrelations-Filter verschaerft (364 → ~30 Patterns)

### Fix
- **Baseline verschaerft**: 0.85 → 0.75 — mehr "immer gleich" Entities werden als trivial gefiltert
- **Top-3 pro Trigger-Entity**: Nur die 3 staerksten Korrelationen pro Trigger-Entity behalten, Rest verworfen
- **Count erhoeht**: same-room 6→8, cross-room 10→14

## 0.7.16 – Korrelations-Qualitaetsfilter (4220 → 364 Patterns)

### Fix
- **Baseline-Filter**: Entities >85% im gleichen State = trivial
- **Bidirektionale Dedup**: A→B und B→A = nur staerkere Richtung
- **Schwellwerte erhoeht**: Count same 4→6, cross 7→10; Confidence same 0.3→0.4, cross 0.5→0.55

## 0.7.15 – Fix Korrelations-Ratio Berechnung (kritischer Bug)

### Fix
- **CRITICAL: Korrelations-Ratio falsch berechnet**: `ratio = count / total` dividierte durch die Summe ALLER Entity/State-Paare statt pro Target-Entity. Bei ~50 Entities wurde jede Ratio um Faktor ~50 verduennt (z.B. 0.75 → 0.015), dadurch scheiterten ALLE 22.103 Paare am Schwellwert. Fix: Ratio wird jetzt pro Target-Entity berechnet
- **Schwellwerte korrigiert**: Zurueck auf 0.7/0.8 (same/cross-room) da Ratios jetzt korrekte Werte liefern

## 0.7.14 – Fix Zeitmuster-Confidence & Korrelations-Schwellwerte

### Fix
- **Zeitmuster-Confidence Formel**: gewichteter Durchschnitt statt Multiplikation
- **expected_days**: 14 → 10 fuer "alle Tage"

### Diagnose
- **Near-Miss-Logging**: Korrelationspaare die knapp am Schwellwert scheitern

## 0.7.13 – Diagnose-Logging & Cross-Room Integration

### Diagnose
- **Zeitmuster-Logging**: INFO-Log zeigt jetzt actionable Events (nach Sensor-Filter), Entity/State-Gruppen, Cluster-Groessen und Confidence-Ablehnungen — hilft bei der Diagnose warum 0 Zeitmuster erkannt werden
- **Korrelations-Logging**: INFO-Log zeigt Trigger-Entity/State-Kombinationen, Paare unter Schwellwert, und Paare mit zu niedriger Confidence

### Fix
- **Cross-Room Korrelationen orphaned**: `detect_cross_room_correlations()` fand 5 Raumpaare, aber die Ergebnisse wurden nie in LearnedPattern-Objekte umgewandelt — Raumpaare werden jetzt als correlation/insight Patterns gespeichert
- **Analyse-Summary erweitert**: Zeigt jetzt alle 4 Pattern-Typen (time, sequence, correlation, cross-room)

## 0.7.12 – Fix Korrelations-Regression

### Fix
- **Korrelations-Filter zu aggressiv**: `MAX_STATE_AGE_SECONDS` von 2 Stunden auf 8 Stunden erhoeht — viele Entities (person, Licht, Klima) halten ihren State stundenlang, der 2h-Filter hat praktisch alle Korrelationen herausgefiltert (0 Korrelationsmuster in Produktion)
- **Debug-Logging**: Zeitmuster-Erkennung protokolliert jetzt Gruppen/Schwellwerte/Ablehnungen fuer bessere Diagnose

## 0.7.11 – Mustererkennung komplett ueberarbeitet (29 Fixes)

### Kritische Fixes
- **Cross-Room Confidence-Formel**: Doppelbestrafung behoben — min_count=20 wirkt jetzt tatsaechlich (vorher waren real ~25 noetig)
- **Mitternachts-Bug**: Clustering und Durchschnittsberechnung um Mitternacht funktionieren jetzt korrekt (zirkulaerer Mittelwert via sin/cos)
- **Confidence sinkt bei Upsert**: Gewichteter Durchschnitt (30% alt / 70% neu) statt `max()` — Muster die schwaecher werden, verlieren jetzt Confidence
- **Executor prueft Schwellwerte**: `DOMAIN_THRESHOLDS` werden vor jeder Ausfuehrung geprueft (z.B. Schloss braucht 0.95 Confidence)
- **Bidirektionale Loop-Erkennung**: Wenn A→B existiert, wird B→A nicht mehr als Pattern akzeptiert (verhindert Endlosschleifen)
- **unavailable/unknown Filter**: HA-Fehlerzustaende werden vor der Analyse komplett herausgefiltert

### Datenqualitaet
- **Korrelationen Room-Aware**: B3-Korrelationen haben jetzt getrennte Schwellwerte fuer same-room (ratio 0.7, count 4) und cross-room (ratio 0.8, count 10)
- **State-Bereinigung**: Korrelationen ignorieren Entity-States die aelter als 8 Stunden sind
- **Exclusions sofort wirksam**: Ausschluesse werden direkt an Detektoren und den Executor weitergegeben (nicht erst bei naechster 6h-Analyse)
- **Bessere Statistik**: Example-Cap von 20 auf 50 erhoeht, Timing-Konsistenz fliesst in Confidence ein, 5s Mindest-Toleranz fuer kurze Delays
- **Automation-Ketten**: Events die durch bestehende HA-Automationen ausgeloest wurden, werden erkannt und uebersprungen

### Performance
- **Analyse-Mutex**: Verhindert parallele Analyselaeufe (war vorher moeglich bei langen Laeufen)
- **Thread-Lock**: Dedup-Cache in app.py ist jetzt thread-safe
- **Pre-Fetch**: Device-Namen werden einmal geladen statt N+1 DB-Queries pro Pattern
- **Cross-Room Pre-Fetch**: ~20.000 DB-Queries auf 1 reduziert
- **Upsert-Cache**: Pattern-Lookup wird pro Session gecacht statt bei jedem Aufruf neu geladen

### Infrastruktur
- **DB-Migration v11**: 9 neue Indexes (PatternMatchLog, PatternExclusion, NotificationLog, RoomDomainState, LearnedScene, Domain)
- **API**: Status "insight" und "rejected" koennen jetzt per PUT gesetzt werden
- **Cross-Room Integration**: `detect_cross_room_correlations()` wird jetzt in der Hauptanalyse aufgerufen
- **Time-Validation**: Ungueltige Zeitstrings im Context Builder werden abgefangen

## 0.7.10 – Raum-Filter fuer Sequence-Patterns

### Intelligentere Mustererkennung
- **Cross-Room-Filter**: Sinnlose Raum-uebergreifende Muster (z.B. "Bewegungsmelder Wohnzimmer → Toiletten-Licht") werden jetzt herausgefiltert
- Same-Room-Muster: normaler Schwellwert (min 7x in 14 Tagen, Confidence >= 0.45)
- Cross-Room-Muster: deutlich strengerer Schwellwert (min 20x, Confidence >= 0.65, Timing-Varianz max 40%)
- Neues `same_room` Flag in pattern_data zur Transparenz

### Fixes
- JSX-Fehler im EnergyPage Konfiguration-Tab behoben (Adjacent elements Fragment)

## 0.7.9 – Phase 4 Feature-Konfiguration

### Umfassende Feature-Einstellungen
- **20 Phase-4 Features** mit detaillierten Konfigurationsoptionen
- Neuer **Konfiguration-Tab** auf Klima-, Gesundheits- und KI-Seite
- Erweiterter Konfiguration-Tab auf der Energie-Seite
- Pro Feature: An/Aus/Auto Toggle + alle relevanten Parameter

### Klima-Konfiguration
- Komfort-Score: Gewichtung (Temp/Feuchte/CO2/Licht), Zielwerte
- Lueftungserinnerung: CO2-Schwellwert, Intervall, Ruhezeiten
- Zirkadiane Beleuchtung: Farbtemperatur-Bereich, Morgen/Abend-Rampe, Nacht-Helligkeit
- Wetter-Alerts: Schweregrad-Filter, Frost/Sturm/Hitze-Toggles, Auto-Rolllaeden

### Gesundheits-Konfiguration
- Schlaf: Empfindlichkeit, Min-Dauer, Temp/Feuchte-Optimalbereiche
- Sanftes Wecken: Rampe, Max-Helligkeit, Rolllaeden/Heizung
- Bildschirmzeit: Tageslimit, Erinnerungsintervall
- Urlaub: Min-Abwesenheit, Urlaubstemperatur, Anwesenheitssimulation
- Besuch: Gaestetemperatur, Vorheizzeit, Auto-Beleuchtung

### Energie-Konfiguration
- Optimierung: Modus (Eco/Balanced/Komfort), Ziel-Einsparung
- PV-Management: Ueberschuss-Schwelle, Min-Dauer, Auto-Lastumschaltung
- Standby-Killer: Schwellwert, Leerlaufzeit, Auto-Abschaltung
- Prognose: Tage, Wetter/Kalender-Integration

### KI-Konfiguration
- Stimmung: Empfindlichkeit, Dashboard-Anzeige
- Gewohnheits-Drift: Erkennungszeitraum, Empfindlichkeit
- Adaptives Timing: Lerngeschwindigkeit, Max-Anpassung, Wochenende
- Kalender: Sync-Intervall, Vorbereitungszeit, Auto-Klima

### Fixes
- Domain-Filter erweitert um RoomDomainState.mode='off' (per-room Deaktivierung)

## 0.7.8 – Bugfix: Muster-Ablehnung & Domain-Ausschluss

### Muster-Ablehnung Fix
- Abgelehnte Muster tauchen nach "Jetzt synchronisieren" nicht mehr wieder auf
- `_upsert_pattern()` prüft jetzt auch rejected/disabled Muster bei Duplikat-Erkennung
- Betrifft alle 3 Mustertypen: time_based, event_chain, correlation

### Domain-Ausschluss Fix
- Deaktivierte Domains (z.B. Klima, Licht) werden jetzt bei Mustererkennung respektiert
- Events von Geräten deaktivierter Domains werden vor der Analyse herausgefiltert
- Kein erneutes Auftauchen von Mustern für ausgeschlossene Domains mehr

## 0.7.7 – UI Polish: Klima & KI Seiten

### ClimatePage Redesign
- Tab-Bar auf MindHome-Standard (`btn btn-sm btn-primary/btn-ghost`) umgestellt
- Page-Header `<h2>` mit Icon hinzugefuegt
- Alle Cards auf `className="card animate-in"` Pattern
- Alle Badges auf `className="badge badge-*"` Pattern
- Empty-States mit zentrierter Card + Icon (statt rohem `<p>`)
- Hardcoded Hex-Farben (`#4CAF50`, `#F44336`, etc.) durch CSS-Variablen ersetzt
- Formular-Inputs mit `bg-tertiary` + `border-color` Theming
- Buttons auf `btn btn-primary`, `btn btn-ghost` Klassen

### AiPage Redesign
- Tab-Bar auf MindHome-Standard umgestellt
- Page-Header `<h2>` mit Icon
- Alle Cards auf `card animate-in` Pattern
- Mood-Statistiken als Grid mit `bg-tertiary` Kacheln + Sensor-Icons
- Screen Time: Progress-Bar mit CSS-Variablen, Entity-Liste mit `border-color`
- Drift/Adaptive: CSS-Variablen (`--warning`, `--info`) statt Hex-Farben
- Saison-Tipps/Kalender: `badge badge-*` Klassen, `card animate-in`
- Empty-States ueberall mit zentrierter Card + passendem Icon

### CSS-Variablen Standardisierung
- `var(--text-secondary)` → `var(--text-muted)` (konsistent mit Theme)
- `var(--border)` → `var(--border-color)`
- `var(--primary)` → `var(--accent-primary)`
- `var(--card-bg)` → `className="card"` (Theme-aware)
- `var(--primary-bg)` → `className="badge badge-info"`

---

## 0.7.6 – Batch 5: Health Dashboard & Finalisierung

### Engines
- **HealthAggregator (#28)**: Aggregiert alle Gesundheitsdaten aus Phase 4 Engines
  - Gesamt-Score (gewichtet: Schlaf 35%, Komfort 30%, Lueftung 20%, Bildschirmzeit 15%)
  - Stuendliche Metric-Snapshots in health_metrics Tabelle
  - Trend-Berechnung (improving/stable/declining) aus 2-Wochen-Vergleich
- **Wochenbericht**: Automatische Empfehlungen basierend auf Metriken
  - Woche-zu-Woche Vergleich mit Richtungsanzeige
  - Kategorien: Schlaf, Komfort, Bildschirmzeit, Gesamt

### API (3 neue Endpunkte)
- GET /api/health/dashboard — Aggregiertes Health-Dashboard
- GET /api/health/weekly-report — Wochenbericht mit Empfehlungen
- GET /api/health/metrics/:type/history — Historische Metriken

### Frontend: Health Dashboard
- **Dashboard-Tab**: 6 Metrik-Kacheln (Schlaf, Komfort, Lueftung, Bildschirmzeit, Stimmung, Wetter)
  - Gesamt-Score mit Farbcodierung (gruen/gelb/rot)
  - Raumklima-Ampel Widget
  - Wetter-Warnungen Preview
- **Wochenbericht-Tab**: 4 Report-Sektionen mit Vorwochen-Vergleich
  - Trend-Pfeile (steigend/fallend/stabil)
  - Empfehlungs-Karten mit Icons

### Bugfixes
- MoodEstimator: brightness=None Vergleich behoben (`NoneType < int`)
- ComfortCalculator/VentilationMonitor: `Device.is_active` → `Device.is_tracked`
- ComfortCalculator/VentilationMonitor: `Device.entity_id` → `Device.ha_entity_id`

### Scheduler
- health_aggregate (1h): Stuendliche Dashboard-Aggregation + Metric-Snapshots

---

## 0.7.5 – Batch 4: KI, Kalender & UX

### Engines (9 Features)
- **MoodEstimator (#15)**: Stimmungserkennung (Relaxed/Active/Cozy/Quiet/Away/Focused)
  - Heuristik aus Media-Player, Lichter, Motion-Sensoren, Klima-Zustaende
  - Haus-Level (kein persoenliches Profiling)
- **ScreenTimeMonitor (#19)**: Bildschirmzeit-Tracking fuer Media-Player
  - Tages-Akkumulation pro Entity, konfigurierbares Limit + Erinnerungen
- **HabitDriftDetector (#12)**: Gewohnheits-Veraenderungen erkennen
  - 2-Wochen Vergleich: Zeitverschiebung, Frequenzaenderungen
  - Woechentliche Analyse
- **AdaptiveTimingManager (#11)**: Lernende Timing-Anpassung
  - Gleitender Durchschnitt der letzten 10 manuellen Ausfuehrungen
  - Auto-Adjustment bei >5 Min Drift mit >5 Samples
- **GradualTransitioner (#23)**: Sanftes Eingreifen
  - Licht: HA transition-Parameter, Klima: Temperatur-Schritte, Cover: Position
- **SeasonalAdvisor (#13)**: Saisonale Empfehlungen
  - 4 Jahreszeiten × 4 Tipps (Energie, Komfort, Sicherheit, Wartung)
  - Wetter-basierter Bonus-Tipp
- **CalendarIntegration (#14)**: HA-Kalender Anbindung
  - Naechste 48h Events, Kalender-Entity Discovery
- **Szenen-Favoriten (#20)**: Stern-Toggle + sortierte Favoriten-Liste
- **Kontext-Benachrichtigungen (#24)**: context_data Modell-Erweiterung

### API (14 neue Endpunkte)
- GET /api/health/mood-estimate
- GET /api/health/screen-time, GET/POST/PUT screen-time/config
- GET /api/patterns/drift
- GET /api/health/adaptive-timing
- GET /api/system/seasonal-tips, GET /api/system/calendar-events, GET calendar-entities
- PUT /api/scenes/:id/favorite, GET /api/scenes/favorites

### Frontend: Neue "KI" Seite
- **Stimmung-Tab**: Stimmungs-Karte mit Icon, Konfidenz, Indikatoren, Statistiken
- **Bildschirmzeit-Tab**: Nutzungs-Balken pro User, Entity-Sessions, Limit-Anzeige
- **Gewohnheiten-Tab**: Drift-Karten mit Zeitverschiebung und Richtung
- **Adaptive-Tab**: Pattern-Anpassungen mit Offset-Anzeige und Sample-Count
- **Saison-Tab**: Saisonale Tipps mit Icons und Kategorien
- **Kalender-Tab**: Event-Liste mit Zeitabstand-Badges

### Frontend: Szenen-Favoriten
- Stern-Icon in Szenen-Liste (Toggle Favorit)

### Scheduler
- screen_time_check (5 Min): Bildschirmzeit + Stimmung
- adaptive_check (15 Min): Timing-Lernen
- weekly_drift (7 Tage): Gewohnheits-Analyse

---

## 0.7.4 – Batch 3: Klima & Umgebung

### Bugfixes
- EventBus: `emit` als Alias fuer `publish` (Batch 2 Engines nutzten falschen Methodennamen)
- Event-Namen auf Dot-Notation (`sleep.detected` statt `sleep_detected`)

### Engines (5 Features)
- **ComfortCalculator (#10)**: Komfort-Score pro Raum (Temp/Feuchtigkeit/CO2/Licht gewichtet 0-100)
- **ComfortCalculator (#17)**: Raumklima-Ampel (gruen/gelb/rot pro Faktor + gesamt)
- **VentilationMonitor (#18)**: Lueftungserinnerung (CO2-Schwellwert ODER Timer, Fenster-Tracking)
- **CircadianLightManager (#27)**: Zirkadiane Beleuchtung mit 2 Modi (MindHome / Hybrid HCL)
  - 3 Lampentypen: dim2warm, tunable_white, standard
  - Event-Overrides: Schlaf, Aufwachen, Gaeste
  - Brightness + Color-Temperature Interpolation auf konfigurierbarer Kurve
- **WeatherAlertManager (#21)**: Wetter-Vorwarnung (Frost/Hitze/Regen/Sturm/Schnee)
  - 2-12h Vorlaufzeit, Deduplizierung, 3 Severity-Level

### API (10 neue Endpunkte)
- GET /api/health/comfort, GET /api/health/comfort/:room_id/history
- GET /api/health/climate-traffic-light
- GET /api/health/ventilation, PUT /api/health/ventilation/:room_id
- GET/POST /api/health/circadian, GET /api/health/circadian/status
- PUT/DELETE /api/health/circadian/:id
- GET /api/health/weather-alerts

### Frontend: Neue "Klima" Seite
- **Komfort-Tab**: Score-Kacheln pro Raum (farbcodiert), Faktor-Details, Ampel-Widget, Verlauf
- **Lueftung-Tab**: Status-Karten (OK/Lueften!/Lueftet), CO2-Werte, Fenster-Tracking
- **Zirkadian-Tab**: Status-Karten, Config CRUD (Modus/Lampentyp/Override), An/Aus Toggle
- **Wetter-Tab**: Warnungs-Karten mit Severity-Badges, Icons, Zeitfenster

### Scheduler
- comfort_check (15 Min): Komfort-Berechnung + Zirkadian-Kurve
- ventilation_check (10 Min): Lueftungs-Monitoring
- weather_check (30 Min): Wetter-Forecast Analyse

---

## 0.7.3 – Batch 2: Schlaf, Routinen & Anwesenheit

### Engines (7 Features)
- **SleepDetector (#4, #16)**: Schlaf-Erkennung via Motion+Licht (20-11 Uhr), Qualitaets-Score (0-100)
- **WakeUpManager (#25)**: Sanftes Wecken mit Licht/Rolladen/Klima-Ramp, pro User konfigurierbar
- **RoutineEngine (#5)**: Morgen-/Abend-Routinen automatisch erkennen + manuell starten
- **RoutineEngine (#6)**: Raumuebergangs-Erkennung (Motion → Transitions-Graph)
- **VisitPreparationManager (#22)**: Besuchs-Vorlagen mit Aktionen (Licht, Temp, Musik)
- **VacationDetector (#29)**: Auto-Urlaubserkennung (>24h weg) + Anwesenheitssimulation

### API (12 neue Endpunkte)
- GET /api/health/sleep, /sleep-quality
- GET/POST/PUT/DELETE /api/health/wakeup
- GET /api/health/routines, POST routines/:id/activate, GET room-transitions
- GET/POST/PUT/DELETE /api/health/visit-preparations, POST :id/activate
- GET /api/health/vacation-status

### Frontend: Neue "Gesundheit" Seite
- **Schlaf-Tab**: Qualitaets-Balkendiagramm (14 Tage), Session-Liste mit Dauer/Score
- **Wecken-Tab**: Wecker CRUD (Licht/Rolladen/Klima Entity + Ramp-Dauer)
- **Routinen-Tab**: Erkannte Routinen mit Steps + "Starten"-Button, Raumuebergaenge
- **Besuch-Tab**: Vorlagen erstellen/aktivieren/loeschen mit Aktionen-Builder
- **Urlaub-Tab**: Status-Karte (Auto-Erkennung, Schwelle, Simulation)

### Scheduler
- sleep_check (5 Min): Schlaf-Erkennung + Weck-Ramp
- visit_vacation_check (10 Min): Besuch-Trigger + Urlaubserkennung
- routine_detect (24h): Routinen aus Mustern clustern

---

## 0.7.2 – Frontend Batch 1 + Feature-Flags UI

### Energie-Dashboard: 3 neue Tabs
- **Optimierung**: Spar-Empfehlungen mit EUR-Einsparpotenzial, Spitzenlast-Hinweise, Top-Verbraucher
- **Solar/PV**: Live-Status (Produktion, Verbrauch, Ueberschuss, Eigenverbrauch-%), PV-Prioritaeten verwalten
- **Prognose**: 7-Tage Balkendiagramm (Prognose vs. Ist), Detailtabelle mit Wetter und Tagestyp

### Bestehende Tabs erweitert
- **Uebersicht**: Quick-Cards fuer Einsparpotenzial, Solar-Status und Empfehlungen
- **Standby**: Live-Standby-Geraete mit Idle-Dauer am Tab-Anfang
- **Konfiguration**: PV-Lastmanagement Checkbox bei aktiviertem Solar

### Settings: Phase 4 Feature-Flags
- 20 Phase 4 Features einzeln steuerbar (Auto/An/Aus)
- Klick-Zyklus: Auto → An → Aus → Auto
- Icons und Labels fuer jedes Feature

---

## 0.7.1 – Batch 1: Energie & Solar

### Energie-Optimierung (#1)
- **Verbrauchsanalyse**: Stündliche Spitzenlast-Erkennung, Tagesvergleich mit 30-Tage-Durchschnitt
- **Top-Verbraucher**: Die 5 größten Stromfresser mit monatlichen Kosten in EUR
- **Spar-Empfehlungen**: Automatische Tipps zur Lastverschiebung

### PV-Lastmanagement (#2)
- **Überschuss-Erkennung**: Echtzeit-Vergleich Produktion vs. Verbrauch
- **Prioritätsliste**: Konfigurierbare Geräte-Reihenfolge bei Überschuss
- **Auto-Aktivierung**: Geräte automatisch einschalten bei PV-Überschuss (>100W)

### Standby-Killer (#3)
- **Standby-Erkennung**: Leistung < Schwellwert über konfigurierbare Idle-Zeit
- **Auto-Off**: Automatisches Abschalten oder Dashboard-Benachrichtigung
- **Live-Status**: Aktuelle Standby-Geräte mit Idle-Dauer

### Energieprognose (#26)
- **7-Tage-Forecast**: Gewichteter Durchschnitt (gleicher Wochentag 2×, Recency-Bonus)
- **Wetter-Integration**: Aktuelle Wetterbedingung wird berücksichtigt
- **Ist-Vergleich**: Gestern-Prognose wird mit tatsächlichem Verbrauch verglichen

### Neue API-Endpunkte
- `GET /api/energy/optimization` — Empfehlungen
- `GET /api/energy/savings` — Einsparpotenzial (EUR/kWh)
- `GET /api/energy/forecast` — 7-Tage-Prognose
- `GET /api/energy/pv-status` — PV Produktion/Verbrauch/Überschuss
- `PUT /api/energy/pv-priorities` — PV-Prioritäten setzen
- `GET /api/energy/standby-status` — Aktuelle Standby-Geräte

### Scheduler
- `energy_check`: Alle 5 Min (Standby + PV-Überschuss)
- `daily_batch`: Täglich (Analyse + Forecast)

---

## 0.7.0 – Phase 4: Smart Health & Energie

### Neue Features
- **Schlaf-Erkennung**: Automatische Schlaf/Wach-Erkennung via Bewegungssensoren
- **Schlaf-Qualität**: Temperatur, CO2, Luftfeuchtigkeit — Schlafbewertung und Tipps
- **Sanftes Wecken**: Zirkadiane Lichtsteuerung als natürlicher Wecker
- **Energie-Optimierung**: PV-Lastmanagement, Standby-Killer, Verbrauchsprognose
- **Komfort-Score**: Raumklima-Bewertung (Temperatur, Luftfeuchtigkeit, CO2)
- **Lüftungserinnerung**: Intelligente Lüftungsvorschläge basierend auf CO2/Fenster-Kontakten
- **Zirkadiane Beleuchtung**: Automatische Farbtemperatur-Anpassung nach Tageszeit
- **Wetter-Alerts**: Frost-, Sturm-, Hitze-Warnungen mit Smart-Home-Reaktionen
- **Bildschirmzeit-Monitor**: Media-Player Nutzungsstatistiken
- **Stimmungserkennung**: Schätzung basierend auf Aktivitätsmuster
- **Besuch-Vorbereitung**: Automatische Szenen bei erwartetem Besuch
- **Gewohnheits-Drift**: Erkennung wenn sich Routinen verschieben
- **Adaptive Reaktionszeit**: KI-optimierte Timing-Anpassung
- **Gesundheits-Dashboard**: Aggregierte Gesundheitsdaten mit Wochenbericht

### Infrastruktur
- **engines/ Modul-Struktur**: 8 neue Engine-Module für Phase 4 Features
- **Feature-Flags**: 20 konfigurierbare Phase 4 Features (auto/true/false)
- **Data Retention**: Automatische nächtliche Bereinigung alter Daten
- **10 neue DB-Modelle**: SleepSession, ComfortScore, HealthMetric, WakeUpConfig, CircadianConfig, EnergyForecast, VentilationReminder, WeatherAlert, VisitPreparation, ScreenTimeConfig
- **Migration v10**: Neue Tabellen und Spalten für Phase 4

### API-Endpunkte
- `GET /api/system/phase4-features` — Feature-Flag Übersicht
- `PUT /api/system/phase4-features/<key>` — Feature aktivieren/deaktivieren
- `GET /api/health/dashboard` — Gesundheits-Dashboard Daten

---

## 0.6.19 – Kalender-Sync, Presence-System & UX-Verbesserungen

### Neue Features
- **Personen bearbeiten**: Name, Rolle und HA-Person direkt in der Personen-Karte editieren
- **Geräte-Zuweisung**: Device-Tracker Entities pro Person zuweisen (Primär/Sekundär/Stationär)
- **Device-Tracker Live-State**: Farbiger Punkt (grün/rot/grau) zeigt Home/Away-Status in Echtzeit
- **Kalender-Export (iCal)**: MindHome-Kalender als URL-Abo für Google Calendar, Apple Calendar oder Outlook
  - Token-geschützt (sicher teilbar)
  - Konfigurierbarer Schicht-Zeitraum (14–365 Tage)
  - Weekday/Homeoffice-Profile als wiederkehrende Events (RRULE)
  - Feiertage, Ferien und Schichten enthalten
- **Kalender-Import (HA)**: Google Calendar, CalDAV und andere HA-Kalender in MindHome synchronisieren
  - Synced Events als blaue Punkte in der Monatsansicht
  - HA-Offline Fallback
- **Kalender-Trigger**: Automatische Aktionen basierend auf Kalender-Events (Keyword-Match → HA-Service)
- **Gast-Modus "Besuch"**: Neuer Presence-Mode für Besuch

### Presence-System
- Default-Modi beim DB-Init: Zuhause, Abwesend, Schlaf, Urlaub, Besuch
- auto_config mit Conditions: first_home, all_away, all_home
- PersonDevice in automatische Presence-Erkennung integriert
- GuestDevice: automatische Pflege von last_seen und visit_count
- Gäste werden in anyone_home Logik gezählt

### UX-Verbesserungen
- Lösch-Bestätigungen für alle Delete-Operationen (9 fehlende ergänzt)
- Auto-Refresh bei Tab-Wechsel (wenn >30s inaktiv)
- Bulk-Pattern-Operationen mit Error-Handling (kein Optimistic Update mehr)
- MindHome für alle HA-Benutzer zugänglich (nicht nur Administratoren)

### Data-Pipeline
- SAMPLING_THRESHOLDS: 13 neue device_classes (signal_strength, distance, gas, wind_speed, etc.)
- ALWAYS_LOG_DOMAINS: 12 neue Domains (water_heater, vacuum, humidifier, valve, siren, etc.)
- Fallback für unbekannte Sensoren: konservativer Schwellwert statt silent drop
- Rate-Limit auf 600 erhöht (Events + HTTP API)
- Dedup-Cache: selektive Bereinigung statt clear()

### Bugfixes
- NotificationLog-Felder korrigiert (title statt title_de, user_id, was_read statt is_read)
- Cache-Header (max-age=3600) + ETag für iCal-Export

---

## 0.6.0 – Phase 3.5: Stabilisierung & Refactoring

### Architektur
- Modulare Blueprint-Architektur: 222 API-Routen in 13 separate Module aufgeteilt
- Neue Infrastruktur-Module: `version.py`, `db.py`, `event_bus.py`, `task_scheduler.py`, `helpers.py`
- Zentrale Versionierung und Dependency Injection

### Bugfixes
- Rate-Limit Middleware korrigiert (doppelte before_request entfernt)
- UTF-8 Encoding durchgängig sichergestellt (Frontend + Backend)
- Fehlende Imports in allen Route-Modulen ergänzt (sys, defaultdict, ha-Referenzen)
- Watchdog und Self-Test als eigenständige Funktionen implementiert
- Debug-Modus Toggle repariert
- Notification Channel Scan: HA Services Format-Kompatibilität
- Frontend Babel Syntax-Fehler behoben

### Verbesserungen
- Startup Self-Test erweitert
- Fehlerbehandlung in allen Routen verbessert
- Saubere Trennung von Concerns (Routes, Models, Helpers)

---

## 0.5.1 – Phase 3 Block A

### Neue Features
- Tagesphasen mit Sonnenstand-Integration
- Schichtkalender & Ferien-Kalender
- Anwesenheits-Modi & Gäste-Verwaltung
- Raum-Szenen (automatisch + manuell)
- Energie-Monitoring & Standby-Erkennung
- Sensor-Fusion & Schwellwerte
- Ruhezeiten, Plugin-Konflikte, Kontext-Tags
- Aktivitäten-Log & Audit Trail

---

## 0.5.0 – Phase 2 Complete

### 68 Verbesserungen
- KI-Mustererkennung (Pattern Engine)
- 3-stufiges Lernsystem (Beobachten → Vorschlagen → Automatisieren)
- Anomalie-Erkennung mit Kontext
- Benachrichtigungssystem (Push, TTS, E-Mail)
- Wochenbericht & Lernstatistiken
- Geräte-Gesundheit & Watchdog
- Automatisierungs-Engine mit Konflikt-Erkennung
- Urlaubsmodus, Debug Mode, Audit Log
- Barrierefreiheit (ARIA, Tastatur, High Contrast)

---

## 0.1.0 – Phase 1: Fundament

- Ein-Klick-Installation als HA Add-on
- Automatische Geräte- und Raumerkennung
- 14 Domain-Plugins
- Onboarding-Wizard
- Personen-Manager mit Rechte-System
- Quick Actions
- Dark/Light Mode, Deutsch/Englisch
- Responsive Design
- WebSocket + REST Echtzeit-Verbindung
