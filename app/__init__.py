import logging

from dotenv import load_dotenv

# Load environment variables before importing Config.
load_dotenv()

from flask import Flask

from app.config import Config
from app.routes.chat import chat_bp
from app.routes.pages import pages_bp
from app.services.record_store import RecordStore


def create_app():
    app = Flask(
        __name__,
        template_folder=Config.TEMPLATE_FOLDER,
        static_folder=Config.STATIC_FOLDER,
    )

    app.config.from_object(Config)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app.register_blueprint(pages_bp)
    app.register_blueprint(chat_bp)

    with app.app_context():
        RecordStore.initialize()

    app.logger.info("Project root: %s", app.root_path)
    app.logger.info("Template folder: %s", app.template_folder)
    app.logger.info("Static folder: %s", app.static_folder)
    app.logger.info("Ollama URL: %s", app.config["OLLAMA_BASE_URL"])
    app.logger.info("Ollama model: %s", app.config["OLLAMA_MODEL"])

    return app

