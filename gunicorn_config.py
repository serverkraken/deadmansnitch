import os
import threading
from app.watchdog_service import check_watchdog

# Gunicorn-Konfiguration für Produktionsumgebungen
bind = "0.0.0.0:5001"
workers = 1  # Wir nutzen nur einen Worker, da wir nur einen watchdog-thread benötigen
threads = 2
worker_class = "gthread"
timeout = 120

# Zugriffslog formatieren
accesslog = "-"  # Stdout
errorlog = "-"  # Stderr
loglevel = os.getenv("LOG_LEVEL", "info")
# Die Variable loglevel wird von Gunicorn automatisch verwendet
# und bestimmt das Log-Level der Gunicorn-Logs

# Sicherstellen, dass die gleiche LOG_LEVEL für den Watchdog verwendet wird
os.environ["LOG_LEVEL"] = loglevel

# Umgebungsvariable setzen, um zu erkennen, dass wir unter Gunicorn laufen
os.environ["RUNNING_IN_GUNICORN"] = "true"

# Variable, um zu verfolgen, ob der Thread bereits gestartet wurde
watchdog_thread_started = False

def when_ready(server):
    """Wird aufgerufen, wenn Gunicorn bereit ist, Anfragen zu verarbeiten."""
    global watchdog_thread_started

    if not watchdog_thread_started:
        server.log.info("Starting watchdog check thread in when_ready hook")
        t = threading.Thread(target=check_watchdog)
        t.daemon = True
        t.start()
        watchdog_thread_started = True
    else:
        server.log.info("Watchdog check thread already running")
