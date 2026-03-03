"""
Brain Callbacks Mixin - Basis-Klasse fuer AssistantBrain.

HINWEIS: Alle Callback-Methoden werden in brain.py ueberschrieben.
Dieses Mixin dient nur noch als Basis-Klasse fuer die Vererbung.
Die erweiterten Implementierungen in brain.py haben:
  - Activity-Checks (_callback_should_speak) mit Quiet Hours
  - Eskalations-Tracking
  - Working-Memory Integration (_remember_exchange)
  - Differenziertes Urgency-Handling (z.B. Koch-Timer = high)
"""

import logging

logger = logging.getLogger(__name__)


class BrainCallbacksMixin:
    """Mixin-Basis fuer AssistantBrain Callbacks.

    Alle Methoden werden in brain.py mit erweiterter Logik ueberschrieben.
    Diese Klasse existiert nur fuer die Vererbungshierarchie.
    """

    pass
