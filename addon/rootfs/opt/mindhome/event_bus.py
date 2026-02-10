# MindHome - event_bus.py | see version.py for version info
"""
Extended Event Bus for cross-plugin communication.
Supports: publish/subscribe, typed events, event history, priority handlers.
Phase 4 ready: plugins can communicate (e.g. sleep detection -> light plugin).
"""

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Callable, Optional, Dict, Any, List

logger = logging.getLogger("mindhome.event_bus")


class Event:
    """Typed event with metadata."""
    
    __slots__ = ('event_type', 'data', 'source', 'timestamp', 'priority')
    
    def __init__(self, event_type: str, data: Any = None, source: str = "system", priority: int = 0):
        self.event_type = event_type
        self.data = data or {}
        self.source = source
        self.timestamp = time.time()
        self.priority = priority

    def __repr__(self):
        return f"Event({self.event_type}, source={self.source})"


class MindHomeEventBus:
    """Central event bus for all MindHome components.
    
    Features:
    - Publish/subscribe with topic patterns
    - Priority-based handler ordering
    - Event history (last N events per type)
    - Thread-safe
    - Wildcard subscriptions (e.g. 'state.*' matches 'state.changed')
    """

    def __init__(self, history_size: int = 100):
        self._handlers: Dict[str, List[dict]] = defaultdict(list)
        self._lock = threading.Lock()
        self._history: deque = deque(maxlen=history_size)
        self._stats = defaultdict(int)

    def subscribe(self, event_type: str, handler: Callable, 
                  priority: int = 0, source_filter: Optional[str] = None) -> str:
        """Subscribe to an event type.
        
        Args:
            event_type: Event type to listen for. Use '*' suffix for wildcard.
            handler: Callback function(event: Event)
            priority: Higher priority handlers run first (default 0)
            source_filter: Only receive events from this source
            
        Returns:
            Subscription ID for unsubscribe
        """
        sub_id = f"{event_type}_{id(handler)}_{time.time()}"
        entry = {
            "id": sub_id,
            "handler": handler,
            "priority": priority,
            "source_filter": source_filter,
        }
        with self._lock:
            self._handlers[event_type].append(entry)
            # Sort by priority (highest first)
            self._handlers[event_type].sort(key=lambda x: -x["priority"])
        logger.debug(f"Subscribed to '{event_type}' (priority={priority})")
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        """Remove a subscription by ID."""
        with self._lock:
            for event_type, handlers in self._handlers.items():
                for i, h in enumerate(handlers):
                    if h["id"] == sub_id:
                        handlers.pop(i)
                        return True
        return False

    def publish(self, event_type: str, data: Any = None, 
                source: str = "system", priority: int = 0):
        """Publish an event to all subscribers.
        
        Args:
            event_type: Type of event (e.g. 'state.changed', 'sleep.detected')
            data: Event payload
            source: Who published this event
            priority: Event priority
        """
        event = Event(event_type, data, source, priority)
        self._history.append(event)
        self._stats[event_type] += 1

        # Collect matching handlers
        handlers_to_call = []
        with self._lock:
            # Exact match
            if event_type in self._handlers:
                handlers_to_call.extend(self._handlers[event_type])
            
            # Wildcard matches (e.g. 'state.*' matches 'state.changed')
            for pattern, handlers in self._handlers.items():
                if pattern.endswith('.*'):
                    prefix = pattern[:-2]
                    if event_type.startswith(prefix) and pattern != event_type:
                        handlers_to_call.extend(handlers)
            
            # Global wildcard '*'
            if '*' in self._handlers and event_type != '*':
                handlers_to_call.extend(self._handlers['*'])

        # Sort all collected handlers by priority
        handlers_to_call.sort(key=lambda x: -x["priority"])

        # Call handlers
        for entry in handlers_to_call:
            # Source filter
            if entry["source_filter"] and event.source != entry["source_filter"]:
                continue
            try:
                entry["handler"](event)
            except Exception as e:
                logger.error(f"Event handler error for '{event_type}': {e}")

    def get_history(self, event_type: Optional[str] = None, limit: int = 50) -> List[dict]:
        """Get recent event history."""
        events = list(self._history)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [
            {"type": e.event_type, "source": e.source, 
             "timestamp": e.timestamp, "data": e.data}
            for e in events[-limit:]
        ]

    def get_stats(self) -> dict:
        """Get event statistics."""
        return {
            "total_events": sum(self._stats.values()),
            "by_type": dict(self._stats),
            "active_subscriptions": sum(len(h) for h in self._handlers.values()),
            "history_size": len(self._history),
        }

    def clear(self):
        """Clear all subscriptions and history."""
        with self._lock:
            self._handlers.clear()
            self._history.clear()
            self._stats.clear()


# Singleton instance
event_bus = MindHomeEventBus()
