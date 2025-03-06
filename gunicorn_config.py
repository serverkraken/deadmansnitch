import os
import threading
import multiprocessing
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


# Funktion, die nach dem Startup des Workers ausgeführt wird
def post_worker_init(worker):
    # Den Watchdog-Check-Thread starten
    threading.Thread(target=check_watchdog, daemon=True).start()
