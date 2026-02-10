# MindHome - routes/frontend.py | see version.py for version info
"""
MindHome Frontend Routes - Static file serving and Ingress support.
"""

import os
import mimetypes
from flask import Blueprint, send_from_directory, redirect, request

frontend_bp = Blueprint("frontend", __name__)

_deps = {}
_static_dir = None


def init_frontend(dependencies):
    global _deps, _static_dir
    _deps = dependencies
    # Determine static directory
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _static_dir = os.path.join(base, "static", "frontend")


@frontend_bp.route("/")
def index():
    """Serve the main page."""
    return send_from_directory(_static_dir, "index.html")


@frontend_bp.route("/static/frontend/<path:filename>")
def serve_frontend_static(filename):
    """Serve frontend static files."""
    return send_from_directory(_static_dir, filename)


@frontend_bp.route("/static/<path:filename>")
def serve_static(filename):
    """Serve general static files."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_dir = os.path.join(base, "static")
    return send_from_directory(static_dir, filename)
