"""
Entry point for the refactored GPUShare application.

Run this script to start the Flask development server.  It uses the
``create_app`` factory defined in ``gpushare_app``.  The resulting
application will serve both the web UI and the JSON API.

Usage::

    python run_secure.py

This script sets ``debug=False`` by default for safer defaults.  You
can enable debug mode by setting the environment variable
``FLASK_ENV=development`` when running this file.
"""

from __future__ import annotations

import os
import sys

# Ensure the application package is on the Python path.  This allows
# running the development server from the project root without
# installing the package system‑wide.
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.join(current_dir, "gpushare_app")
if parent_dir not in sys.path:
    sys.path.insert(0, current_dir)

from gpushare_app import create_app  # noqa: E402


app = create_app()

if __name__ == "__main__":
    # Note: do not enable debug mode in production
    app.run(host="0.0.0.0", port=5000, debug=False)