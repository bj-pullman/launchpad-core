from modules.core.auth.blueprints import auth_bp
from modules.core.auth import routes  # noqa: F401

# Adjust this import to match your actual project
from launchpad.apps.launchpad_ui.blueprints import launchpad_ui_bp


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(launchpad_ui_bp)