"""
Brain Humanizers Mixin — Query-Result Humanizer fuer AssistantBrain.

Wandelt rohe HA-Abfrageergebnisse in natuerliche JARVIS-Sprache um.
Extrahiert aus brain.py zur Reduktion der Dateigroesse.
"""

import logging
import re
from typing import Optional

from . import config as cfg
from .config import get_person_title

logger = logging.getLogger(__name__)


class BrainHumanizersMixin:
    """Mixin fuer Query-Result Humanization in AssistantBrain."""

    # ------------------------------------------------------------------
    # Query-Result Humanizer (Fallback wenn LLM-Feedback-Loop fehlschlaegt)
    # ------------------------------------------------------------------

    def _humanize_query_result(self, func_name: str, raw: str) -> str:
        """Wandelt rohe Query-Ergebnisse in natuerliche JARVIS-Sprache um.

        Template-basiert, kein LLM noetig. Greift nur als Fallback wenn der
        LLM-Feedback-Loop keine Antwort produziert hat.
        """
        try:
            if func_name == "get_weather":
                return self._humanize_weather(raw)
            elif func_name == "get_calendar_events":
                return self._humanize_calendar(raw)
            elif func_name == "get_entity_state":
                return self._humanize_entity_state(raw)
            elif func_name == "get_room_climate":
                return self._humanize_room_climate(raw)
            elif func_name == "get_house_status":
                return self._humanize_house_status(raw)
            elif func_name in ("get_alarms", "set_wakeup_alarm", "cancel_alarm"):
                return self._humanize_alarms(raw)
            elif func_name == "get_lights":
                return self._humanize_lights(raw)
            elif func_name == "get_switches":
                return self._humanize_switches(raw)
            elif func_name == "get_covers":
                return self._humanize_covers(raw)
            elif func_name == "get_media":
                return self._humanize_media(raw)
            elif func_name == "get_climate":
                return self._humanize_climate_list(raw)
        except Exception as e:
            logger.warning(
                "Humanize fehlgeschlagen für %s: %s", func_name, e, exc_info=True
            )
        # Kein Template vorhanden — Rohdaten zurueckgeben
        return raw

    def _humanize_weather(self, raw: str) -> str:
        """Wetter-Rohdaten → JARVIS-Stil Antwort.

        Verarbeitet AKTUELL- und VORHERSAGE-Zeilen aus get_weather.
        """
        from datetime import datetime as _dt

        _conditions_map = {
            "bewoelkt": "bewölkt",
            "bewölkt": "bewölkt",
            "sonnig": "sonnig",
            "wolkenlos": "wolkenlos",
            "klare nacht": "klare Nacht",
            "regen": "regnerisch",
            "teilweise bewoelkt": "teilweise bewölkt",
            "teilweise bewölkt": "teilweise bewölkt",
            "nebel": "neblig",
            "schnee": "verschneit",
            "gewitter": "gewittrig",
            "windig": "windig",
            "starkregen": "Starkregen",
        }

        # --- Aktuelle Wetter-Zeile extrahieren ---
        lines = raw.strip().split("\n")
        current_line = ""
        forecast_lines = []
        for line in lines:
            if line.startswith("AKTUELL:"):
                current_line = line
            elif line.startswith("VORHERSAGE"):
                forecast_lines.append(line)
        if not current_line:
            current_line = lines[0] if lines else raw

        # Temperatur extrahieren
        temp_match = re.search(r"(-?\d+)[.,]?\d*\s*°C", current_line)
        if not temp_match:
            return raw
        temp = int(temp_match.group(1))

        # Condition extrahieren
        condition = ""
        cl_lower = current_line.lower()
        for key, val in _conditions_map.items():
            if key in cl_lower:
                condition = val
                break

        # Wind extrahieren
        wind_match = re.search(
            r"Wind\s+(?:aus\s+)?(\w+)\s+(?:mit\s+)?(\d+)[.,]?\d*\s*km/h",
            current_line,
            re.IGNORECASE,
        )
        if not wind_match:
            wind_match = re.search(
                r"Wind\s+(\d+)[.,]?\d*\s*km/h\s+aus\s+(\w+)",
                current_line,
                re.IGNORECASE,
            )
            if wind_match:
                wind_speed = int(wind_match.group(1))
                wind_dir = wind_match.group(2)
            else:
                wind_speed = 0
                wind_dir = ""
        else:
            wind_dir = wind_match.group(1)
            wind_speed = int(wind_match.group(2))

        # JARVIS-Stil: natuerlich, gerundet, knapp
        if condition:
            result = f"{temp} Grad, {condition}."
        else:
            result = f"{temp} Grad draussen."

        # Windrichtung: HA liefert englische Abkuerzungen (N, NE, SSW etc.)
        _wind_dir_map = {
            "n": "Nord",
            "nne": "Nord-Nordost",
            "ne": "Nordost",
            "ene": "Ost-Nordost",
            "e": "Ost",
            "ese": "Ost-Südost",
            "se": "Südost",
            "sse": "Süd-Südost",
            "s": "Süd",
            "ssw": "Süd-Südwest",
            "sw": "Südwest",
            "wsw": "West-Südwest",
            "w": "West",
            "wnw": "West-Nordwest",
            "nw": "Nordwest",
            "nnw": "Nord-Nordwest",
            # Ausgeschriebene englische Varianten
            "north": "Nord",
            "northeast": "Nordost",
            "east": "Ost",
            "southeast": "Südost",
            "south": "Süd",
            "southwest": "Südwest",
            "west": "West",
            "northwest": "Nordwest",
        }
        if wind_dir:
            wind_dir = _wind_dir_map.get(wind_dir.lower(), wind_dir)
        # Wind nur erwaehnen wenn spuerbar (> 10 km/h)
        if wind_speed > 10 and wind_dir:
            result += f" Wind aus {wind_dir}."

        # Kontext-Kommentar (JARVIS-Persoenlichkeit)
        if temp <= 0:
            result += (
                f" Handschuhe empfohlen, {get_person_title(self._current_person)}."
            )
        elif temp <= 5:
            result += " Jacke empfohlen."
        elif temp >= 30:
            result += f" Genuegend trinken, {get_person_title(self._current_person)}."

        # --- Forecast-Zeilen verarbeiten ---
        if forecast_lines:
            _weekdays = [
                "Montag",
                "Dienstag",
                "Mittwoch",
                "Donnerstag",
                "Freitag",
                "Samstag",
                "Sonntag",
            ]
            fc_parts = []
            for fc_line in forecast_lines[:3]:
                date_m = re.search(r"VORHERSAGE\s+(\d{4}-\d{2}-\d{2}):", fc_line)
                temp_hi = re.search(r"Hoch\s+(-?\d+)", fc_line)
                temp_lo = re.search(r"Tief\s+(-?\d+)", fc_line)
                cond_m = re.search(r":\s+(\w[\w\s]*?),\s+Hoch", fc_line)
                precip_m = re.search(r"Niederschlag\s+(\d+[.,]?\d*)\s*mm", fc_line)

                if not (date_m and temp_hi):
                    continue

                # Datum → Wochentag
                try:
                    d = _dt.strptime(date_m.group(1), "%Y-%m-%d")
                    day_name = _weekdays[d.weekday()]
                except (ValueError, IndexError):
                    day_name = date_m.group(1)

                fc_text = f"{day_name}: {temp_hi.group(1)}"
                if temp_lo:
                    fc_text += f"/{temp_lo.group(1)}"
                fc_text += " Grad"
                if cond_m:
                    fc_cond = cond_m.group(1).strip()
                    # Condition uebersetzen wenn moeglich
                    fc_cond_mapped = _conditions_map.get(fc_cond.lower(), fc_cond)
                    fc_text += f", {fc_cond_mapped}"
                if precip_m:
                    try:
                        precip_val = float(precip_m.group(1).replace(",", "."))
                        if precip_val > 0:
                            fc_text += f", {precip_m.group(1)} mm Regen"
                    except ValueError:
                        pass
                fc_parts.append(fc_text)

            if len(fc_parts) == 1:
                result += f" {fc_parts[0]}."
            elif fc_parts:
                result += " " + ". ".join(fc_parts) + "."

        return result

    def _humanize_calendar(self, raw: str) -> str:
        """Kalender-Rohdaten → JARVIS-Stil Antwort."""
        if not raw or not raw.strip():
            return raw

        raw_upper = raw.upper()

        # Zeitkontext aus Header bestimmen ("TERMINE MORGEN", "TERMINE HEUTE", ...)
        if "MORGEN" in raw_upper:
            prefix_single = "Morgen steht"
            prefix_multi = "Morgen stehen"
            prefix_free = f"Morgen ist frei, {get_person_title(self._current_person)}."
        elif "WOCHE" in raw_upper:
            prefix_single = "Diese Woche steht"
            prefix_multi = "Diese Woche stehen"
            prefix_free = (
                f"Die Woche ist frei, {get_person_title(self._current_person)}."
            )
        else:
            prefix_single = "Heute steht"
            prefix_multi = "Heute stehen"
            prefix_free = (
                f"Heute ist nichts geplant, {get_person_title(self._current_person)}."
            )

        # "KEINE TERMINE" Varianten
        if "KEINE TERMINE" in raw_upper or "(0)" in raw:
            return prefix_free

        # Alle "HH:MM | Titel" Muster extrahieren (funktioniert ein- und mehrzeilig)
        pattern = r"(\d{1,2}:\d{2})\s*\|\s*(.+?)(?:\n|$)"
        matches = re.findall(pattern, raw)

        # Ganztaegige Termine separat erfassen
        ganztag_pattern = r"ganztaegig\s*\|\s*(.+?)(?:\n|$)"
        ganztag_matches = re.findall(ganztag_pattern, raw, re.IGNORECASE)

        if not matches and not ganztag_matches:
            return raw

        events = []
        for time_str, title in matches:
            title = title.strip()
            # Ort/Info-Suffix entfernen (nach erstem |)
            if " | " in title:
                title = title.split(" | ")[0].strip()
            # Uhrzeit natuerlicher formatieren
            h, m = time_str.split(":")
            h = int(h)
            m = int(m)
            if m == 0:
                time_natural = f"um {h} Uhr"
            else:
                time_natural = f"um {h} Uhr {m}"
            events.append(f"{title} {time_natural}")

        for title in ganztag_matches:
            events.append(title.strip())

        if len(events) == 1:
            return f"{prefix_single} {events[0]} an, {get_person_title(self._current_person)}."
        listing = ", ".join(events[:-1]) + f" und {events[-1]}"
        return f"{prefix_multi} {len(events)} Termine an: {listing}."

    def _humanize_entity_state(self, raw: str) -> str:
        """Entity-Status — JARVIS-Stil: knapp und praezise."""
        if len(raw) < 80:
            return raw
        lines = raw.strip().split("\n")
        if len(lines) <= 3:
            return raw
        summary = " ".join(l.strip().lstrip("- ") for l in lines[:3] if l.strip())
        if len(lines) > 3:
            summary += f" — plus {len(lines) - 3} weitere Datenpunkte."
        return summary

    def _humanize_room_climate(self, raw: str) -> str:
        """Raum-Klima — JARVIS-Stil mit Messwert-Praezision."""
        temp_m = re.search(r"(-?\d+[.,]?\d*)\s*°?C", raw)
        hum_m = re.search(r"(\d+[.,]?\d*)\s*%", raw)
        parts = []
        if temp_m:
            parts.append(f"{temp_m.group(1)} Grad")
        if hum_m:
            parts.append(f"Luftfeuchtigkeit {hum_m.group(1)}%")
        if parts:
            return ", ".join(parts) + "."
        return raw

    def _humanize_house_status(self, raw: str) -> str:
        """Haus-Status in natuerliche JARVIS-Sprache.

        Respektiert house_status.detail_level aus settings.yaml:
          kompakt:      Nur Zusammenfassung (Zahlen, keine Namen)
          normal:       Bereiche mit Namen (Default)
          ausfuehrlich: Alle Details (Helligkeit, Soll-Temp, Medientitel etc.)
        """
        if not raw or not raw.strip():
            return "Alles ruhig im Haus."

        hs_cfg = cfg.yaml_config.get("house_status", {})
        detail = hs_cfg.get("detail_level", "normal")

        lines = raw.strip().split("\n")
        parts = []
        title = get_person_title(self._current_person)

        _sec_map = {
            "disarmed": "Alarmanlage aus",
            "armed_home": "Alarmanlage aktiv (zuhause)",
            "armed_away": "Alarmanlage aktiv (abwesend)",
            "armed_night": "Alarmanlage aktiv (Nacht)",
            "triggered": "ALARM AUSGELOEST",
            "unknown": "",
        }

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # --- Anwesenheit ---
            if line.startswith("Zuhause:"):
                names = line.replace("Zuhause:", "").strip()
                if names:
                    if detail == "kompakt":
                        count = len([n.strip() for n in names.split(",") if n.strip()])
                        parts.append(
                            f"{count} Person{'en' if count > 1 else ''} zuhause"
                        )
                    else:
                        parts.append(
                            f"{names} ist zuhause"
                            if "," not in names
                            else f"{names} sind zuhause"
                        )
            elif line.startswith("Unterwegs:"):
                names = line.replace("Unterwegs:", "").strip()
                if names and detail != "kompakt":
                    parts.append(f"{names} unterwegs")

            # --- Temperaturen ---
            elif line.startswith("Temperaturen:"):
                temps = line.replace("Temperaturen:", "").strip()
                if temps:
                    if detail == "kompakt":
                        all_temps = re.findall(r"(-?\d+[.,]?\d*)\s*°C", temps)
                        if all_temps:
                            parts.append(f"{all_temps[0]}°C")
                    elif detail == "normal":
                        cleaned = re.sub(r"\s*\(Soll [^)]+\)", "", temps)
                        parts.append(cleaned)
                    else:
                        parts.append(temps)

            # --- Wetter ---
            elif line.startswith("Wetter:"):
                weather = line.replace("Wetter:", "").strip()
                if weather:
                    if detail == "kompakt":
                        temp_m = re.search(r"(-?\d+)\s*°C", weather)
                        cond = (
                            weather.split(",")[0].strip() if "," in weather else weather
                        )
                        if temp_m:
                            parts.append(f"Draussen {temp_m.group(1)}°C, {cond}")
                        else:
                            parts.append(f"Draussen: {cond}")
                    else:
                        parts.append(f"Draussen: {weather}")

            # --- Lichter ---
            elif line.startswith("Lichter an:"):
                lights = line.replace("Lichter an:", "").strip()
                if lights:
                    light_list = [l.strip() for l in lights.split(",")]
                    if detail == "kompakt":
                        parts.append(
                            f"{len(light_list)} Licht{'er' if len(light_list) > 1 else ''} an"
                        )
                    elif detail == "normal":
                        names_only = [
                            re.sub(r":\s*\d+%", "", l).strip() for l in light_list
                        ]
                        if len(names_only) <= 4:
                            parts.append(f"Lichter an: {', '.join(names_only)}")
                        else:
                            parts.append(f"{len(names_only)} Lichter an")
                    else:
                        parts.append(f"Lichter an: {lights}")
            elif line.startswith("Alle Lichter aus"):
                parts.append("Alle Lichter aus")

            # --- Sicherheit ---
            elif line.startswith("Sicherheit:"):
                sec = line.replace("Sicherheit:", "").strip().lower()
                sec_text = _sec_map.get(sec, sec)
                if sec_text:
                    parts.append(sec_text)

            # --- Medien ---
            elif line.startswith("Medien aktiv:"):
                media = line.replace("Medien aktiv:", "").strip()
                if media:
                    if detail == "kompakt":
                        parts.append("Medien aktiv")
                    else:
                        parts.append(f"Medien: {media}")

            # --- Offene Fenster/Tueren ---
            elif line.startswith("Offen:"):
                items = line.replace("Offen:", "").strip()
                if items:
                    if detail == "kompakt":
                        count = len([i.strip() for i in items.split(",") if i.strip()])
                        parts.append(f"{count} offen")
                    else:
                        parts.append(f"Offen: {items}")

            # --- Offline ---
            elif line.startswith("Offline"):
                if detail == "kompakt":
                    m = re.search(r"\((\d+)\)", line)
                    if m:
                        parts.append(f"{m.group(1)} Geraete offline")
                else:
                    parts.append(line)

        if not parts:
            return f"Alles ruhig im Haus, {title}."

        return ". ".join(parts) + "."

    def _humanize_alarms(self, raw: str) -> str:
        """Wecker-Daten — JARVIS-Stil."""
        if not raw or "keine wecker" in raw.lower():
            return "Kein Wecker gestellt."

        # "Wecker gestellt: morgen um 08:15 Uhr." (set_wakeup_alarm result)
        set_match = re.search(r"Wecker gestellt:\s*(.+)", raw, re.IGNORECASE)
        if set_match:
            return f"Wecker steht auf {set_match.group(1).strip()}."

        # "Aktive Wecker:\n  - Wecker: 08:15 Uhr (einmalig)" (get_alarms result)
        entries = re.findall(r"-\s*(.+?):\s*(\d{1,2}:\d{2})\s*Uhr\s*\(([^)]+)\)", raw)
        if entries:
            parts = []
            for label, time_str, repeat in entries:
                label = label.strip()
                if repeat == "einmalig":
                    parts.append(f"{time_str} Uhr")
                else:
                    parts.append(f"{time_str} Uhr ({repeat})")
            if len(parts) == 1:
                return f"Wecker auf {parts[0]}."
            return f"{len(parts)} Wecker aktiv: " + ", ".join(parts) + "."

        return raw

    def _humanize_lights(self, raw: str) -> str:
        """Licht-Status — JARVIS-Stil."""
        lines = raw.strip().split("\n")
        on_lights = []
        for line in lines:
            if ": on" in line:
                name = line.lstrip("- ").split("[")[0].strip()
                bri_match = re.search(r"\((\d+)%\)", line)
                if bri_match:
                    on_lights.append(f"{name} auf {bri_match.group(1)}%")
                else:
                    on_lights.append(name)
        if not on_lights:
            return "Alles dunkel."
        if len(on_lights) == 1:
            return f"{on_lights[0]}."
        return f"{len(on_lights)} Lichter aktiv: {', '.join(on_lights)}."

    def _humanize_switches(self, raw: str) -> str:
        """Schalter/Steckdosen-Status — JARVIS-Stil."""
        lines = raw.strip().split("\n")
        on_items = []
        for line in lines:
            if ": on" in line:
                name = line.lstrip("- ").split("[")[0].strip()
                on_items.append(name)
        if not on_items:
            return "Alle Schalter aus."
        if len(on_items) == 1:
            return f"{on_items[0]} laeuft."
        return f"{len(on_items)} Geraete aktiv: {', '.join(on_items)}."

    def _humanize_covers(self, raw: str) -> str:
        """Rollladen-Status — JARVIS-Stil."""
        lines = raw.strip().split("\n")
        open_items = []
        for line in lines:
            if ": open" in line or "offen" in line.lower():
                name = line.lstrip("- ").split("[")[0].strip()
                pos_match = re.search(r"\((\d+)%\)", line)
                if pos_match:
                    open_items.append(f"{name} auf {pos_match.group(1)}%")
                else:
                    open_items.append(name)
        if not open_items:
            return "Alle Rolllaeden unten."
        if len(open_items) == 1:
            return f"{open_items[0]} ist offen."
        return f"{len(open_items)} Rolllaeden offen: {', '.join(open_items)}."

    def _humanize_media(self, raw: str) -> str:
        """Media-Player Status — JARVIS-Stil."""
        lines = raw.strip().split("\n")
        playing = []
        for line in lines:
            if "playing" in line.lower() or "spielt" in line.lower():
                name = line.lstrip("- ").split("[")[0].strip()
                playing.append(name)
        if not playing:
            return "Stille im Haus."
        if len(playing) == 1:
            return f"{playing[0]} laeuft."
        return f"Medien aktiv: {', '.join(playing)}."

    def _humanize_climate_list(self, raw: str) -> str:
        """Klima-Geraete Status — JARVIS-Stil."""
        lines = raw.strip().split("\n")
        active = []
        for line in lines:
            temp_m = re.search(r"(-?\d+[.,]?\d*)\s*°?C", line)
            name = line.lstrip("- ").split("[")[0].split(":")[0].strip()
            if temp_m and name:
                active.append(f"{name}: {temp_m.group(1)}°C")
        if active:
            return ", ".join(active) + "."
        if len(raw) < 120:
            return raw
        return "\n".join(lines[:5])

    # ------------------------------------------------------------------
    # Phase 6C: Vergleichs- und Anomalie-Formatierung
    # ------------------------------------------------------------------

    def format_comparison(
        self, current_value: float, previous_value: float, unit: str = ""
    ) -> str:
        """Formatiert einen Vergleich zwischen aktuellem und vorherigem Wert.

        Gibt einen String im Stil '18°C, gestern 21°C (↓3°)' zurueck.
        """
        delta = current_value - previous_value
        if delta == 0:
            return f"{current_value}{unit}, unveraendert"

        arrow = "↑" if delta > 0 else "↓"
        abs_delta = abs(delta)
        # Ganzzahl-Formatierung wenn kein Nachkomma noetig
        fmt_cur = (
            f"{current_value:.0f}"
            if current_value == int(current_value)
            else f"{current_value:.1f}"
        )
        fmt_prev = (
            f"{previous_value:.0f}"
            if previous_value == int(previous_value)
            else f"{previous_value:.1f}"
        )
        fmt_delta = (
            f"{abs_delta:.0f}" if abs_delta == int(abs_delta) else f"{abs_delta:.1f}"
        )

        return f"{fmt_cur}{unit}, vorher {fmt_prev}{unit} ({arrow}{fmt_delta}{unit})"

    def highlight_anomaly(self, values: dict, label: str = "") -> Optional[str]:
        """Hebt ungewoehnliche Zustaende hervor.

        Erkennt wenn eine Mehrheit von Geraeten in einem unerwarteten Zustand ist
        und gibt einen String wie '3/4 Tueren offen — ungewoehnlich' zurueck.

        Args:
            values: Dict von {name: state} wobei state True/False oder 'on'/'off'/'open'/'closed'
            label: Bezeichnung fuer die Geraetegruppe (z.B. 'Tueren', 'Fenster')
        """
        if not values:
            return None

        total = len(values)
        if total < 2:
            return None

        # Zaehle "aktive" Zustaende (on, open, True)
        active_states = {"on", "open", "true", "offen"}
        active_count = 0
        for state in values.values():
            state_str = str(state).lower()
            if state_str in active_states or state_str == "True":
                active_count += 1

        # Anomalie: Mehr als die Haelfte aktiv
        if active_count > total / 2 and active_count >= 2:
            group = label or "Geraete"
            return f"{active_count}/{total} {group} offen — ungewoehnlich"

        return None

    def format_delta_context(self, changes: list[dict]) -> str:
        """Formatiert Zustandsaenderungen seit der letzten Interaktion.

        Args:
            changes: Liste von Dicts mit 'entity', 'old_state', 'new_state', optional 'room'

        Returns:
            Zusammenfassung der Aenderungen als natuerlicher Text.
        """
        if not changes:
            return ""

        parts = []
        for change in changes[:5]:  # Max 5 Aenderungen anzeigen
            entity = change.get("entity", "Unbekannt")
            old = change.get("old_state", "?")
            new = change.get("new_state", "?")
            room = change.get("room", "")
            room_suffix = f" ({room})" if room else ""
            parts.append(f"{entity}{room_suffix}: {old} → {new}")

        suffix = ""
        if len(changes) > 5:
            suffix = f" — und {len(changes) - 5} weitere"

        return "Seit letzter Interaktion: " + ", ".join(parts) + suffix + "."

    # ------------------------------------------------------------------
    # Device-Command Bestaetigungs-Humanizer
    # ------------------------------------------------------------------

    def _humanize_device_command(self, text: str, executed: list) -> str:
        """Generiert eine natuerliche Bestaetigung fuer ausgefuehrte Geraetebefehle.

        Template-basiert, kein LLM noetig. Variiert leicht fuer natuerlichere Antworten.
        """
        import random

        title = get_person_title() or "Sir"

        # Sammle ausgefuehrte Aktionen nach Typ
        actions_by_type: dict[str, list[str]] = {}
        for act in executed:
            func = act["function"]
            args = act.get("args", {})
            room = args.get("room", "")
            action = args.get("action", args.get("state", ""))

            # Menschenlesbare Beschreibung generieren
            desc = self._describe_action(func, action, room)
            if desc:
                actions_by_type.setdefault(func, []).append(desc)

        if not actions_by_type:
            return f"Erledigt, {title}."

        # Alle Beschreibungen zusammenfuegen
        all_descs = []
        for descs in actions_by_type.values():
            all_descs.extend(descs)

        action_text = (
            " und ".join(all_descs)
            if len(all_descs) <= 2
            else (", ".join(all_descs[:-1]) + f" und {all_descs[-1]}")
        )

        # Variierte Bestaetigungen
        templates = [
            f"Erledigt, {title} — {action_text}.",
            f"Wird gemacht, {title}. {action_text}.",
            f"Selbstverständlich, {title}. {action_text}.",
            f"{action_text.capitalize()} — erledigt, {title}.",
        ]

        return random.choice(templates)

    @staticmethod
    def _describe_action(func: str, action: str, room: str) -> Optional[str]:
        """Generiert eine menschenlesbare Beschreibung einer Geraeteaktion."""
        # Deutsche Grammatik: "im" (Maskulin/Neutrum) vs. "in der" (Feminin)
        _feminine_rooms = {
            "küche",
            "kueche",
            "garage",
            "werkstatt",
            "waschküche",
            "waschkueche",
        }
        if room and room != "all":
            r_cap = room.capitalize()
            room_suffix = (
                f" in der {r_cap}"
                if room.lower() in _feminine_rooms
                else f" im {r_cap}"
            )
        elif room == "all":
            room_suffix = " überall"
        else:
            room_suffix = ""

        _action_map = {
            "set_cover": {
                "close": f"Rollläden{room_suffix} heruntergefahren",
                "open": f"Rollläden{room_suffix} hochgefahren",
                "stop": f"Rollläden{room_suffix} gestoppt",
            },
            "set_light": {
                "on": f"Licht{room_suffix} eingeschaltet",
                "off": f"Licht{room_suffix} ausgeschaltet",
            },
            "set_switch": {
                "on": f"Gerät{room_suffix} eingeschaltet",
                "off": f"Gerät{room_suffix} ausgeschaltet",
            },
            "set_climate": {},
        }

        func_map = _action_map.get(func, {})
        if action in func_map:
            return func_map[action]

        # Climate-Sonderfall
        if func == "set_climate":
            return f"Heizung{room_suffix} angepasst"

        return None
