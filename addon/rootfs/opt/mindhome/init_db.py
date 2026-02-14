# MindHome init_db v0.6.2 (2026-02-10) - init_db.py
"""
MindHome - Database Initialization
Creates tables and populates default data on first run.
"""

import os
import sys
import logging
from models import (
    init_database, get_engine, get_session,
    Domain, QuickAction, SystemSetting, UserRole, User,
    NotificationSetting, NotificationType, PresenceMode,
)

logger = logging.getLogger("mindhome.init_db")


def create_default_domains(session):
    """Create all 14 domain plugins."""
    domains = [
        {
            "name": "light",
            "display_name_de": "Licht",
            "display_name_en": "Light",
            "icon": "mdi:lightbulb",
            "description_de": "Lampen, Dimmer, Farblichter, LED-Streifen",
            "description_en": "Lamps, dimmers, color lights, LED strips"
        },
        {
            "name": "climate",
            "display_name_de": "Klima & Heizung",
            "display_name_en": "Climate & Heating",
            "icon": "mdi:thermostat",
            "description_de": "Thermostate, Heizung, Klimaanlage",
            "description_en": "Thermostats, heating, air conditioning"
        },
        {
            "name": "cover",
            "display_name_de": "Rollläden & Abdeckungen",
            "display_name_en": "Covers & Blinds",
            "icon": "mdi:blinds",
            "description_de": "Rollläden, Jalousien, Markisen, Garagentore",
            "description_en": "Blinds, shutters, awnings, garage doors"
        },
        {
            "name": "presence",
            "display_name_de": "Anwesenheit",
            "display_name_en": "Presence",
            "icon": "mdi:home-account",
            "description_de": "Wer ist zuhause? Handy-Tracking, BLE, Router, Proximität",
            "description_en": "Who is home? Phone tracking, BLE, router, proximity"
        },
        {
            "name": "media",
            "display_name_de": "Medien",
            "display_name_en": "Media",
            "icon": "mdi:television",
            "description_de": "TV, Lautsprecher, Mediaplayer",
            "description_en": "TV, speakers, media players"
        },
        {
            "name": "door_window",
            "display_name_de": "Türen & Fenster",
            "display_name_en": "Doors & Windows",
            "icon": "mdi:door-open",
            "description_de": "Kontaktsensoren für Türen und Fenster",
            "description_en": "Contact sensors for doors and windows"
        },
        {
            "name": "motion",
            "display_name_de": "Bewegungsmelder",
            "display_name_en": "Motion Sensors",
            "icon": "mdi:motion-sensor",
            "description_de": "Bewegungserkennung pro Raum",
            "description_en": "Motion detection per room"
        },
        {
            "name": "energy",
            "display_name_de": "Strom & Energie",
            "display_name_en": "Power & Energy",
            "icon": "mdi:lightning-bolt",
            "description_de": "Stromverbrauch, Leistungsmessung",
            "description_en": "Power consumption, energy monitoring"
        },
        {
            "name": "weather",
            "display_name_de": "Wetter",
            "display_name_en": "Weather",
            "icon": "mdi:weather-partly-cloudy",
            "description_de": "Externe Wetterdaten als Einflussfaktor",
            "description_en": "External weather data as influence factor"
        },
        {
            "name": "lock",
            "display_name_de": "Schlösser & Sicherheit",
            "display_name_en": "Locks & Security",
            "icon": "mdi:lock",
            "description_de": "Türschlösser, Alarmanlagen",
            "description_en": "Door locks, alarm systems"
        },
        {
            "name": "switch",
            "display_name_de": "Schaltbare Steckdosen",
            "display_name_en": "Smart Plugs",
            "icon": "mdi:power-socket-de",
            "description_de": "Schaltbare Steckdosen mit/ohne Leistungsmessung",
            "description_en": "Smart plugs with/without power monitoring"
        },
        {
            "name": "air_quality",
            "display_name_de": "Luftqualität",
            "display_name_en": "Air Quality",
            "icon": "mdi:air-filter",
            "description_de": "CO2, VOC, Feuchtigkeit, Feinstaub",
            "description_en": "CO2, VOC, humidity, particulate matter"
        },
        {
            "name": "ventilation",
            "display_name_de": "Lüftungsanlage",
            "display_name_en": "Ventilation",
            "icon": "mdi:fan",
            "description_de": "KWL, Lüftungsanlage mit Wärmerückgewinnung",
            "description_en": "HRV, ventilation with heat recovery"
        },
        {
            "name": "solar",
            "display_name_de": "PV-Anlage",
            "display_name_en": "Solar PV",
            "icon": "mdi:solar-power",
            "description_de": "Photovoltaik, Erzeugung, Eigenverbrauch, Einspeisung",
            "description_en": "Photovoltaics, generation, self-consumption, feed-in"
        },
        {
            "name": "bed_occupancy",
            "display_name_de": "Bettbelegung",
            "display_name_en": "Bed Occupancy",
            "icon": "mdi:bed",
            "description_de": "Bettbelegungssensoren, Schlaftracking",
            "description_en": "Bed occupancy sensors, sleep tracking"
        },
        {
            "name": "seat_occupancy",
            "display_name_de": "Sitzbelegung",
            "display_name_en": "Seat Occupancy",
            "icon": "mdi:seat",
            "description_de": "Sitzbelegungssensoren fuer Sofa, Stuhl, etc.",
            "description_en": "Seat occupancy sensors for sofa, chair, etc."
        },
        {
            "name": "vacuum",
            "display_name_de": "Saugroboter",
            "display_name_en": "Robot Vacuum",
            "icon": "mdi:robot-vacuum",
            "description_de": "Saugroboter, automatische Reinigung",
            "description_en": "Robot vacuums, automatic cleaning"
        },
        {
            "name": "system",
            "display_name_de": "System",
            "display_name_en": "System",
            "icon": "mdi:cellphone-link",
            "description_de": "Telefone, Rechner, Akkus, Netzwerk",
            "description_en": "Phones, computers, batteries, network"
        },
        {
            "name": "motion_control",
            "display_name_de": "Bewegungsmelder Steuerung",
            "display_name_en": "Motion Sensor Control",
            "icon": "mdi:motion-sensor-off",
            "description_de": "Bewegungsmelder ein-/ausschalten, Empfindlichkeit",
            "description_en": "Toggle motion sensors on/off, sensitivity"
        },
        {
            "name": "humidifier",
            "display_name_de": "Luftbefeuchter",
            "display_name_en": "Humidifier",
            "icon": "mdi:air-humidifier",
            "description_de": "Luftbefeuchter und Entfeuchter, Ziel-Luftfeuchtigkeit",
            "description_en": "Humidifiers and dehumidifiers, target humidity"
        },
        {
            "name": "camera",
            "display_name_de": "Kamera",
            "display_name_en": "Camera",
            "icon": "mdi:cctv",
            "description_de": "Überwachungskameras, Aufnahme, Live-Stream",
            "description_en": "Security cameras, recording, live stream"
        },
    ]

    created = 0
    for domain_data in domains:
        existing = session.query(Domain).filter_by(name=domain_data["name"]).first()
        if existing:
            continue
        domain = Domain(**domain_data)
        session.add(domain)
        created += 1

    session.commit()
    print(f"Created {created} domains ({len(domains) - created} already existed).")


def create_default_quick_actions(session):
    """Create system quick actions."""
    actions = [
        {
            "name_de": "Alles aus",
            "name_en": "All off",
            "icon": "mdi:power-off",
            "action_data": {"type": "all_off", "targets": "all"},
            "sort_order": 1,
            "is_system": True
        },
        {
            "name_de": "Ich gehe jetzt",
            "name_en": "I'm leaving",
            "icon": "mdi:exit-run",
            "action_data": {"type": "leaving_home", "targets": "all"},
            "sort_order": 2,
            "is_system": True
        },
        {
            "name_de": "Ich bin zurück",
            "name_en": "I'm back",
            "icon": "mdi:home",
            "action_data": {"type": "arriving_home", "targets": "all"},
            "sort_order": 3,
            "is_system": True
        },
        {
            "name_de": "Gäste kommen",
            "name_en": "Guests arriving",
            "icon": "mdi:account-group",
            "action_data": {"type": "guest_mode_on", "targets": "all"},
            "sort_order": 4,
            "is_system": True
        },
        {
            "name_de": "Not-Aus",
            "name_en": "Emergency Stop",
            "icon": "mdi:alert-octagon",
            "action_data": {"type": "emergency_stop", "targets": "all"},
            "sort_order": 5,
            "is_system": True
        },
    ]

    created = 0
    for action_data in actions:
        existing = session.query(QuickAction).filter_by(name_de=action_data["name_de"]).first()
        if existing:
            logger.info(f"Seed skip (exists): {action_data['name_de']}")
            continue
        action = QuickAction(**action_data)
        session.add(action)
        created += 1

    session.commit()
    print(f"Created {created} quick actions ({len(actions) - created} skipped).")


def create_default_settings(session):
    """Create default system settings."""
    settings = [
        {
            "key": "onboarding_completed",
            "value": "false",
            "description_de": "Ob der Einrichtungsassistent abgeschlossen wurde",
            "description_en": "Whether the onboarding wizard has been completed"
        },
        {
            "key": "system_mode",
            "value": "normal",
            "description_de": "Systemmodus: normal, vacation, guest, emergency_stop",
            "description_en": "System mode: normal, vacation, guest, emergency_stop"
        },
        {
            "key": "scan_interval_seconds",
            "value": "30",
            "description_de": "Wie oft MindHome Daten von HA abfragt (Sekunden)",
            "description_en": "How often MindHome polls data from HA (seconds)"
        },
        {
            "key": "learning_phase_1_days",
            "value": "14",
            "description_de": "Dauer der Beobachtungsphase (Tage)",
            "description_en": "Duration of observation phase (days)"
        },
        {
            "key": "learning_phase_2_days",
            "value": "14",
            "description_de": "Dauer der Vorschlagsphase (Tage)",
            "description_en": "Duration of suggestion phase (days)"
        },
        {
            "key": "prediction_confidence_threshold",
            "value": "0.7",
            "description_de": "Minimale Confidence für automatische Aktionen (0.0 - 1.0)",
            "description_en": "Minimum confidence for automatic actions (0.0 - 1.0)"
        },
        {
            "key": "theme",
            "value": "dark",
            "description_de": "Frontend Theme: dark oder light",
            "description_en": "Frontend theme: dark or light"
        },
        {
            "key": "view_mode",
            "value": "simple",
            "description_de": "Ansichtsmodus: simple oder advanced",
            "description_en": "View mode: simple or advanced"
        },
    ]

    for setting_data in settings:
        setting = SystemSetting(**setting_data)
        session.add(setting)

    session.commit()
    print(f"Created {len(settings)} system settings.")


def create_default_presence_modes(session):
    """Create default presence modes (Zuhause, Abwesend, Schlaf, Urlaub, Besuch)."""
    defaults = [
        {"name_de": "Zuhause", "name_en": "Home", "icon": "mdi-home", "color": "#4CAF50", "priority": 1, "is_system": True, "trigger_type": "auto", "auto_config": {"condition": "first_home"}},
        {"name_de": "Abwesend", "name_en": "Away", "icon": "mdi-exit-run", "color": "#FF9800", "priority": 2, "is_system": True, "trigger_type": "auto", "auto_config": {"condition": "all_away"}},
        {"name_de": "Schlaf", "name_en": "Sleep", "icon": "mdi-sleep", "color": "#3F51B5", "priority": 3, "is_system": True, "trigger_type": "auto", "auto_config": {"condition": "all_home", "time_range": {"start": "22:00", "end": "06:00"}}},
        {"name_de": "Urlaub", "name_en": "Vacation", "icon": "mdi-beach", "color": "#00BCD4", "priority": 4, "is_system": True, "trigger_type": "manual"},
        {"name_de": "Besuch", "name_en": "Guests", "icon": "mdi-account-group", "color": "#9C27B0", "priority": 5, "is_system": True, "trigger_type": "manual"},
    ]
    created = 0
    for m in defaults:
        existing = session.query(PresenceMode).filter_by(name_de=m["name_de"]).first()
        if existing:
            continue
        session.add(PresenceMode(**m, is_active=True))
        created += 1
    session.commit()
    print(f"Created {created} default presence modes ({len(defaults) - created} already existed).")


def main():
    """Initialize the database with all defaults."""
    print("=" * 60)
    print("MindHome - Database Initialization")
    print("=" * 60)

    engine = get_engine()
    init_database(engine)
    print("Database tables created.")

    session = get_session(engine)

    try:
        create_default_domains(session)
        create_default_quick_actions(session)
        create_default_settings(session)
        create_default_presence_modes(session)
        print("=" * 60)
        print("Database initialization complete!")
        print("=" * 60)
    except Exception as e:
        session.rollback()
        print(f"Error during initialization: {e}")
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
