import os
import threading
from app.watchdog_service import check_watchdog

# Gunicorn-Konfiguration für Produktionsumgebungen
bind = "0.0.0.0:5001"
# workers = multiprocessing.cpu_count() * 2 + 1  # Empfohlene Anzahl von Workern
workers = 1
threads = 2
worker_class = "gthread"  # Gevent oder gthread sind gute Optionen für Anwendungen mit lange laufenden Anfragen
timeout = 120  # Längerer Timeout für mögliche lange Webhook-Anfragen

# Zugriffslog formatieren
accesslog = "-"  # Stdout
errorlog = "-"  # Stderr
loglevel = os.getenv("LOG_LEVEL", "info")

# Umgebungsvariable setzen, um zu erkennen, dass wir unter Gunicorn laufen
os.environ["RUNNING_IN_GUNICORN"] = "true"


# Die ursprüngliche post_worker_init Funktion wird in Gunicorn nicht automatisch aufgerufen!
# Wir brauchen stattdessen diese Hooks:
def when_ready(server):
    """Wird aufgerufen, wenn Gunicorn bereit ist, Anfragen zu verarbeiten."""
    server.log.info("Starting watchdog check thread in when_ready hook")
    t = threading.Thread(target=check_watchdog)
    t.daemon = True
    t.start()


# Alternative Hook-Methode
def post_fork(server, worker):
    """Wird nach dem Forking eines Worker-Prozesses aufgerufen."""
    server.log.info(f"Starting watchdog check thread in worker {worker.pid}")
    t = threading.Thread(target=check_watchdog)
    t.daemon = True
    t.start()
