from flask import Flask


def create_app():
    app = Flask(__name__)

    from app.routes.ubereats import ubereats_bp

    app.register_blueprint(ubereats_bp)

    return app
