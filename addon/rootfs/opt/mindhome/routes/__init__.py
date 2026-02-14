# MindHome - routes/__init__.py | see version.py for version info
"""
Flask Blueprint registration.
All API routes are organized in separate modules.
"""

from flask import Blueprint


def register_blueprints(app, dependencies):
    """Register all route blueprints with shared dependencies.
    
    Args:
        app: Flask app instance
        dependencies: dict with shared objects:
            - ha: HAConnection instance
            - engine: SQLAlchemy engine
            - domain_manager: DomainManager instance (or None)
            - event_bus: EventBus instance
            - state_logger: StateLogger instance
            - pattern_scheduler: PatternScheduler instance
            - automation_scheduler: AutomationScheduler instance
            - domain_plugins: DOMAIN_PLUGINS config dict
    """
    from routes.system import system_bp, init_system
    from routes.rooms import rooms_bp, init_rooms
    from routes.devices import devices_bp, init_devices
    from routes.users import users_bp, init_users
    from routes.patterns import patterns_bp, init_patterns
    from routes.automation import automation_bp, init_automation
    from routes.energy import energy_bp, init_energy
    from routes.notifications import notifications_bp, init_notifications
    from routes.domains import domains_bp, init_domains
    from routes.scenes import scenes_bp, init_scenes
    from routes.presence import presence_bp, init_presence
    from routes.schedules import schedules_bp, init_schedules
    from routes.frontend import frontend_bp, init_frontend
    from routes.health import health_bp, init_health

    # Initialize each module with dependencies
    init_system(dependencies)
    init_rooms(dependencies)
    init_devices(dependencies)
    init_users(dependencies)
    init_patterns(dependencies)
    init_automation(dependencies)
    init_energy(dependencies)
    init_notifications(dependencies)
    init_domains(dependencies)
    init_scenes(dependencies)
    init_presence(dependencies)
    init_schedules(dependencies)
    init_frontend(dependencies)
    init_health(dependencies)

    # Register blueprints
    app.register_blueprint(system_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(patterns_bp)
    app.register_blueprint(automation_bp)
    app.register_blueprint(energy_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(domains_bp)
    app.register_blueprint(scenes_bp)
    app.register_blueprint(presence_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(frontend_bp)
    app.register_blueprint(health_bp)
