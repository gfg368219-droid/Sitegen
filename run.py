"""Combined runner: starts the Flask web app and the Discord bot together."""
import os
import sys
import threading
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger("run")


def run_web():
    from app import app
    port = int(os.getenv("PORT", 5000))
    log.info("[WEB] Starting Flask on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


def run_bot():
    from bot import main
    log.info("[BOT] Starting Discord bot")
    main()


if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web, name="flask-web", daemon=True)
    web_thread.start()
    log.info("[RUN] Web thread started")
    run_bot()  # blocks until bot exits
