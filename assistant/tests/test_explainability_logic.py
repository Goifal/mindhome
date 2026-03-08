"""
Tests for pure functions from ExplainabilityEngine and ActionPlanner.

All logic is copied as standalone functions — no project imports required.
"""

import pytest
from collections import deque


# ---------------------------------------------------------------------------
# Standalone copies of the functions under test
# ---------------------------------------------------------------------------

# --- ExplainabilityEngine ---

def explain_last(decisions, n=1):
    if not decisions:
        return []
    return list(decisions)[-n:]


def explain_by_domain(decisions, domain, n=5):
    return [d for d in reversed(decisions) if d.get("domain") == domain][:n]


def explain_by_action(decisions, action_keyword, n=5):
    kw = action_keyword.lower()
    return [
        d for d in reversed(decisions)
        if kw in d.get("action", "").lower() or kw in d.get("reason", "").lower()
    ][:n]


def format_explanation(decision, detail_level="normal"):
    action = decision.get("action", "Unbekannte Aktion")
    reason = decision.get("reason", "Kein Grund angegeben")
    trigger = decision.get("trigger", "")
    time_str = decision.get("time_str", "")
    confidence = decision.get("confidence", 1.0)

    trigger_labels = {
        "user_command": "auf deinen Befehl",
        "automation": "durch eine Automation",
        "anticipation": "weil ich ein Muster erkannt habe",
        "proactive": "proaktiv",
        "schedule": "nach Zeitplan",
        "sensor": "wegen Sensordaten",
        "conflict": "zur Konfliktloesung",
    }
    trigger_text = trigger_labels.get(trigger, "")

    parts = [f"Ich habe '{action}' ausgefuehrt"]
    if trigger_text:
        parts[0] += f" ({trigger_text})"
    parts.append(f"Grund: {reason}")

    if detail_level == "verbose" and confidence < 1.0:
        parts.append(f"Konfidenz: {confidence:.0%}")

    if time_str:
        parts.append(f"Zeitpunkt: {time_str}")

    return ". ".join(parts) + "."


def get_stats(decisions):
    if not decisions:
        return {"total": 0, "domains": {}, "triggers": {}}
    domains = {}
    triggers = {}
    for d in decisions:
        dom = d.get("domain", "unknown")
        trig = d.get("trigger", "unknown")
        domains[dom] = domains.get(dom, 0) + 1
        triggers[trig] = triggers.get(trig, 0) + 1
    return {"total": len(decisions), "domains": domains, "triggers": triggers}


# --- ActionPlanner ---

COMPLEX_KEYWORDS = [
    "alles", "fertig machen", "vorbereiten",
    "gehe weg", "fahre weg", "verreise", "urlaub",
    "routine", "morgenroutine", "abendroutine",
    "wenn ich", "falls ich", "bevor ich",
    "zuerst", "danach", "und dann", "ausserdem",
    "komplett", "ueberall", "in allen",
    "party", "besuch kommt", "gaeste",
]

QUESTION_STARTS = ("was ", "wie ", "warum ", "wo ", "wer ", "wann ", "welch")


def is_complex_request(text):
    text_lower = text.lower().strip()
    if text_lower.endswith("?") or text_lower.startswith(QUESTION_STARTS):
        return False
    return any(kw in text_lower for kw in COMPLEX_KEYWORDS)


def get_narration_text(func_name, func_args):
    narrations = {
        "set_light": lambda a: (
            f"Licht {a.get('room', '')} dimmt..."
            if a.get("state") == "on" and a.get("brightness", 100) < 50
            else ""
        ),
        "set_cover": lambda a: (
            f"Rolladen {a.get('room', '')} faehrt..."
            if a.get("position", 50) != 50
            else ""
        ),
        "set_climate": lambda a: "",
        "activate_scene": lambda a: "",
        "play_media": lambda a: "",
    }
    generator = narrations.get(func_name)
    if generator:
        return generator(func_args)
    return ""


def get_rollback_info(func_name, func_args):
    rollback_map = {
        "set_light": lambda args: (
            "set_light",
            {"room": args.get("room", ""), "state": "off" if args.get("state") == "on" else "on"},
        ),
        "set_climate": lambda args: (
            "set_climate",
            {"room": args.get("room", ""), "temperature": args.get("temperature", 21)},
        ),
    }
    gen = rollback_map.get(func_name)
    if gen:
        return gen(func_args)
    return (None, None)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _decision(action="Licht an", reason="Befehl", domain="light",
              trigger="user_command", confidence=1.0, time_str=""):
    """Convenience factory for decision dicts."""
    return {
        "action": action,
        "reason": reason,
        "domain": domain,
        "trigger": trigger,
        "confidence": confidence,
        "time_str": time_str,
    }


# ---------------------------------------------------------------------------
# 1. explain_last
# ---------------------------------------------------------------------------

class TestExplainLast:
    def test_empty_list(self):
        assert explain_last([]) == []

    def test_empty_deque(self):
        assert explain_last(deque()) == []

    def test_single_item_default_n(self):
        d = [_decision()]
        result = explain_last(d)
        assert len(result) == 1
        assert result[0]["action"] == "Licht an"

    @pytest.mark.parametrize("n, expected_count", [
        (1, 1),
        (2, 2),
        (3, 3),
    ])
    def test_n_items(self, n, expected_count):
        decisions = [_decision(action=f"action_{i}") for i in range(5)]
        result = explain_last(decisions, n=n)
        assert len(result) == expected_count
        # Should return the LAST n items
        assert result[-1]["action"] == "action_4"

    def test_n_more_than_available(self):
        decisions = [_decision(action="a"), _decision(action="b")]
        result = explain_last(decisions, n=10)
        assert len(result) == 2

    def test_works_with_deque(self):
        decisions = deque([_decision(action=f"d{i}") for i in range(4)])
        result = explain_last(decisions, n=2)
        assert len(result) == 2
        assert result[0]["action"] == "d2"
        assert result[1]["action"] == "d3"


# ---------------------------------------------------------------------------
# 2. explain_by_domain
# ---------------------------------------------------------------------------

class TestExplainByDomain:
    def test_filter_matching_domain(self):
        decisions = [
            _decision(domain="light"),
            _decision(domain="climate"),
            _decision(domain="light"),
        ]
        result = explain_by_domain(decisions, "light")
        assert len(result) == 2
        assert all(d["domain"] == "light" for d in result)

    def test_no_matches(self):
        decisions = [_decision(domain="light"), _decision(domain="climate")]
        assert explain_by_domain(decisions, "media") == []

    def test_empty_decisions(self):
        assert explain_by_domain([], "light") == []

    def test_limit(self):
        decisions = [_decision(domain="light", action=f"a{i}") for i in range(10)]
        result = explain_by_domain(decisions, "light", n=3)
        assert len(result) == 3

    def test_returns_most_recent_first(self):
        decisions = [
            _decision(domain="light", action="first"),
            _decision(domain="climate", action="mid"),
            _decision(domain="light", action="last"),
        ]
        result = explain_by_domain(decisions, "light")
        assert result[0]["action"] == "last"
        assert result[1]["action"] == "first"


# ---------------------------------------------------------------------------
# 3. explain_by_action
# ---------------------------------------------------------------------------

class TestExplainByAction:
    def test_keyword_in_action(self):
        decisions = [
            _decision(action="Licht einschalten", reason="Test"),
            _decision(action="Heizung an", reason="Kalt"),
        ]
        result = explain_by_action(decisions, "licht")
        assert len(result) == 1
        assert result[0]["action"] == "Licht einschalten"

    def test_keyword_in_reason(self):
        decisions = [
            _decision(action="Etwas tun", reason="Wegen Licht"),
        ]
        result = explain_by_action(decisions, "licht")
        assert len(result) == 1

    def test_case_insensitive(self):
        decisions = [_decision(action="LICHT AN")]
        assert len(explain_by_action(decisions, "licht")) == 1
        assert len(explain_by_action(decisions, "LICHT")) == 1

    def test_no_matches(self):
        decisions = [_decision(action="Heizung", reason="Kalt")]
        assert explain_by_action(decisions, "rolladen") == []

    def test_limit(self):
        decisions = [_decision(action=f"Licht {i}") for i in range(10)]
        result = explain_by_action(decisions, "licht", n=3)
        assert len(result) == 3

    def test_returns_most_recent_first(self):
        decisions = [
            _decision(action="Licht erste"),
            _decision(action="Licht letzte"),
        ]
        result = explain_by_action(decisions, "licht")
        assert result[0]["action"] == "Licht letzte"


# ---------------------------------------------------------------------------
# 4. format_explanation
# ---------------------------------------------------------------------------

class TestFormatExplanation:
    @pytest.mark.parametrize("trigger, expected_label", [
        ("user_command", "auf deinen Befehl"),
        ("automation", "durch eine Automation"),
        ("anticipation", "weil ich ein Muster erkannt habe"),
        ("proactive", "proaktiv"),
        ("schedule", "nach Zeitplan"),
        ("sensor", "wegen Sensordaten"),
        ("conflict", "zur Konfliktloesung"),
    ])
    def test_trigger_labels(self, trigger, expected_label):
        d = _decision(trigger=trigger)
        result = format_explanation(d)
        assert expected_label in result

    def test_no_trigger(self):
        d = _decision(trigger="")
        result = format_explanation(d)
        # Should not contain any parenthesised trigger text
        assert "(" not in result
        assert "Ich habe 'Licht an' ausgefuehrt" in result
        assert "Grund: Befehl" in result

    def test_unknown_trigger(self):
        d = _decision(trigger="something_new")
        result = format_explanation(d)
        assert "(" not in result

    def test_verbose_low_confidence(self):
        d = _decision(confidence=0.75)
        result = format_explanation(d, detail_level="verbose")
        assert "Konfidenz: 75%" in result

    def test_verbose_full_confidence_omits_konfidenz(self):
        d = _decision(confidence=1.0)
        result = format_explanation(d, detail_level="verbose")
        assert "Konfidenz" not in result

    def test_normal_detail_omits_konfidenz(self):
        d = _decision(confidence=0.5)
        result = format_explanation(d, detail_level="normal")
        assert "Konfidenz" not in result

    def test_with_time_str(self):
        d = _decision(time_str="2026-03-08 14:30")
        result = format_explanation(d)
        assert "Zeitpunkt: 2026-03-08 14:30" in result

    def test_without_time_str(self):
        d = _decision(time_str="")
        result = format_explanation(d)
        assert "Zeitpunkt" not in result

    def test_defaults_for_missing_keys(self):
        result = format_explanation({})
        assert "Unbekannte Aktion" in result
        assert "Kein Grund angegeben" in result

    def test_ends_with_period(self):
        result = format_explanation(_decision())
        assert result.endswith(".")


# ---------------------------------------------------------------------------
# 5. get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_empty(self):
        result = get_stats([])
        assert result == {"total": 0, "domains": {}, "triggers": {}}

    def test_single_domain(self):
        decisions = [_decision(domain="light", trigger="user_command")]
        result = get_stats(decisions)
        assert result["total"] == 1
        assert result["domains"] == {"light": 1}
        assert result["triggers"] == {"user_command": 1}

    def test_multiple_domains_and_triggers(self):
        decisions = [
            _decision(domain="light", trigger="user_command"),
            _decision(domain="light", trigger="automation"),
            _decision(domain="climate", trigger="user_command"),
            _decision(domain="climate", trigger="sensor"),
            _decision(domain="climate", trigger="sensor"),
        ]
        result = get_stats(decisions)
        assert result["total"] == 5
        assert result["domains"] == {"light": 2, "climate": 3}
        assert result["triggers"] == {"user_command": 2, "automation": 1, "sensor": 2}

    def test_missing_keys_default_to_unknown(self):
        decisions = [{}]
        result = get_stats(decisions)
        assert result["domains"] == {"unknown": 1}
        assert result["triggers"] == {"unknown": 1}


# ---------------------------------------------------------------------------
# 6. is_complex_request
# ---------------------------------------------------------------------------

class TestIsComplexRequest:
    @pytest.mark.parametrize("text", [
        "Mach alles aus",
        "Wohnung fertig machen zum Schlafen",
        "Bitte vorbereiten fuer Gaeste",
        "Ich fahre weg morgen",
        "Starte die Morgenroutine",
        "Wenn ich nach Hause komme, Licht an",
        "Zuerst Licht an und dann Heizung hoch",
        "Mach ueberall das Licht an",
        "Es kommt Besuch kommt heute Abend",
        "Urlaub ab morgen",
    ])
    def test_complex_keywords_match(self, text):
        assert is_complex_request(text) is True

    @pytest.mark.parametrize("text", [
        "Was ist die Temperatur?",
        "Wie warm ist es?",
        "Warum ist das Licht an?",
        "Wo ist mein Handy?",
        "Wer hat das Licht angemacht?",
        "Wann geht die Sonne unter?",
        "Welche Lichter sind an?",
    ])
    def test_questions_with_w_words_excluded(self, text):
        assert is_complex_request(text) is False

    @pytest.mark.parametrize("text", [
        "Ist alles in Ordnung?",
        "Laeuft die Routine schon?",
    ])
    def test_questions_with_question_mark_excluded(self, text):
        assert is_complex_request(text) is False

    @pytest.mark.parametrize("text", [
        "Licht an",
        "Heizung auf 22 Grad",
        "Rolladen runter",
        "Spiel etwas Musik",
    ])
    def test_normal_text_not_complex(self, text):
        assert is_complex_request(text) is False

    def test_case_insensitive(self):
        assert is_complex_request("MACH ALLES AUS") is True

    def test_whitespace_stripped(self):
        assert is_complex_request("  alles aus  ") is True


# ---------------------------------------------------------------------------
# 7. get_narration_text
# ---------------------------------------------------------------------------

class TestGetNarrationText:
    def test_set_light_dimming(self):
        result = get_narration_text("set_light", {"state": "on", "brightness": 30, "room": "Wohnzimmer"})
        assert "Licht" in result
        assert "Wohnzimmer" in result
        assert "dimmt" in result

    def test_set_light_not_dimming_full_brightness(self):
        result = get_narration_text("set_light", {"state": "on", "brightness": 100, "room": "Kueche"})
        assert result == ""

    def test_set_light_not_dimming_state_off(self):
        result = get_narration_text("set_light", {"state": "off", "brightness": 30, "room": "Bad"})
        assert result == ""

    def test_set_light_no_brightness_defaults_to_100(self):
        # brightness defaults to 100, so >= 50 => no narration
        result = get_narration_text("set_light", {"state": "on", "room": "Flur"})
        assert result == ""

    def test_set_cover_moving(self):
        result = get_narration_text("set_cover", {"position": 0, "room": "Schlafzimmer"})
        assert "Rolladen" in result
        assert "Schlafzimmer" in result
        assert "faehrt" in result

    def test_set_cover_at_neutral_position(self):
        result = get_narration_text("set_cover", {"position": 50, "room": "Buero"})
        assert result == ""

    def test_set_cover_default_position_is_50(self):
        # No position provided, defaults to 50 => no narration
        result = get_narration_text("set_cover", {"room": "Buero"})
        assert result == ""

    @pytest.mark.parametrize("func_name", ["set_climate", "activate_scene", "play_media"])
    def test_known_functions_return_empty(self, func_name):
        result = get_narration_text(func_name, {"room": "Test"})
        assert result == ""

    def test_unknown_function(self):
        result = get_narration_text("unknown_func", {"key": "value"})
        assert result == ""


# ---------------------------------------------------------------------------
# 8. get_rollback_info
# ---------------------------------------------------------------------------

class TestGetRollbackInfo:
    def test_set_light_on_to_off(self):
        func, args = get_rollback_info("set_light", {"room": "Wohnzimmer", "state": "on"})
        assert func == "set_light"
        assert args["room"] == "Wohnzimmer"
        assert args["state"] == "off"

    def test_set_light_off_to_on(self):
        func, args = get_rollback_info("set_light", {"room": "Kueche", "state": "off"})
        assert func == "set_light"
        assert args["room"] == "Kueche"
        assert args["state"] == "on"

    def test_set_climate_preserves_temperature(self):
        func, args = get_rollback_info("set_climate", {"room": "Bad", "temperature": 24})
        assert func == "set_climate"
        assert args["room"] == "Bad"
        assert args["temperature"] == 24

    def test_set_climate_default_temperature(self):
        func, args = get_rollback_info("set_climate", {"room": "Flur"})
        assert func == "set_climate"
        assert args["temperature"] == 21

    def test_unknown_function_returns_none(self):
        func, args = get_rollback_info("play_media", {"song": "test"})
        assert func is None
        assert args is None

    def test_set_light_missing_room_defaults_empty(self):
        func, args = get_rollback_info("set_light", {"state": "on"})
        assert args["room"] == ""
