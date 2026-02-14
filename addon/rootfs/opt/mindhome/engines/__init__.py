# MindHome - engines/__init__.py | see version.py for version info
"""
Phase 4 Engine modules.
New Phase 4 classes live here to keep automation_engine.py manageable.
"""

from engines.sleep import SleepDetector, WakeUpManager
from engines.energy import EnergyOptimizer, StandbyMonitor, EnergyForecaster
from engines.circadian import CircadianLightManager
from engines.comfort import ComfortCalculator, VentilationMonitor, ScreenTimeMonitor
from engines.routines import RoutineEngine, MoodEstimator
from engines.weather_alerts import WeatherAlertManager
from engines.visit import VisitPreparationManager

__all__ = [
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
]
