# MindHome - engines/__init__.py | see version.py for version info
"""
Phase 4 + Phase 5 Engine modules.
New classes live here to keep automation_engine.py manageable.
"""

# Phase 4
from engines.sleep import SleepDetector, WakeUpManager
from engines.energy import EnergyOptimizer, StandbyMonitor, EnergyForecaster
from engines.circadian import CircadianLightManager
from engines.comfort import ComfortCalculator, VentilationMonitor, ScreenTimeMonitor
from engines.routines import RoutineEngine, MoodEstimator
from engines.weather_alerts import WeatherAlertManager
from engines.visit import VisitPreparationManager, VacationDetector
from engines.adaptive import HabitDriftDetector, AdaptiveTimingManager, GradualTransitioner, SeasonalAdvisor, CalendarIntegration
from engines.health_dashboard import HealthAggregator

# Phase 5
from engines.fire_water import FireResponseManager, WaterLeakManager
from engines.camera_security import SecurityCameraManager
from engines.access_control import AccessControlManager, GeoFenceManager
from engines.special_modes import PartyMode, CinemaMode, HomeOfficeMode, NightLockdown, EmergencyProtocol

__all__ = [
    # Phase 4
    "SleepDetector",
    "WakeUpManager",
    "EnergyOptimizer",
    "StandbyMonitor",
    "EnergyForecaster",
    "CircadianLightManager",
    "ComfortCalculator",
    "VentilationMonitor",
    "ScreenTimeMonitor",
    "RoutineEngine",
    "MoodEstimator",
    "WeatherAlertManager",
    "VisitPreparationManager",
    "VacationDetector",
    "HabitDriftDetector",
    "AdaptiveTimingManager",
    "GradualTransitioner",
    "SeasonalAdvisor",
    "CalendarIntegration",
    "HealthAggregator",
    # Phase 5
    "FireResponseManager",
    "WaterLeakManager",
    "SecurityCameraManager",
    "AccessControlManager",
    "GeoFenceManager",
    "PartyMode",
    "CinemaMode",
    "HomeOfficeMode",
    "NightLockdown",
    "EmergencyProtocol",
]
