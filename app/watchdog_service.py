import time
import os
import json
import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, abort
from threading import Thread, Lock

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("watchdog_service")

# Flask initialisieren
webapp = Flask(__name__)

# SQLite initialisieren
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "watchdog.db")
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

# Create table if not exists
cursor.execute("""
CREATE TABLE IF NOT EXISTS watchdog_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    last_watchdog_time REAL,
    status TEXT,
    total_received INTEGER,
    invalid_received INTEGER
)
""")
conn.commit()

# Konfiguration aus Umgebungsvariablen laden
google_chat_webhook_url = os.getenv("GOOGLE_CHAT_WEBHOOK_URL")
watchdog_timeout = int(os.getenv("WATCHDOG_TIMEOUT", 3600))  # Default auf 1 Stunde
expected_alertname = os.getenv("EXPECTED_ALERTNAME", "Watchdog")
cleanup_token = os.getenv("CLEANUP_TOKEN", "default_secret_token")

# Lock für thread-sichere Operationen
lock = Lock()


def format_timestamp(timestamp):
    """Formatiert einen Unix-Timestamp als lesbare Datetime."""
    if timestamp == 0:
        return "never"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def send_google_chat_notification(message):
    """Sendet eine Benachrichtigung an Google Chat."""
    if google_chat_webhook_url is None:
        logger.error("GOOGLE_CHAT_WEBHOOK_URL Umgebungsvariable ist nicht gesetzt.")
        return False

    headers = {"Content-Type": "application/json; charset=UTF-8"}
    data = {"text": message}

    try:
        response = requests.post(
            google_chat_webhook_url, headers=headers, json=data, timeout=10
        )
        if response.status_code == 200:
            logger.info("Notification sent successfully")
            logger.debug(f"Notification content: {message}")
            return True
        else:
            logger.error(
                f"Failed to send notification. Status code: {response.status_code}"
            )
            return False
    except Exception as e:
        logger.error(f"Exception sending notification: {e}")
        return False


def get_watchdog_state():
    """Lädt den aktuellen Watchdog-Status aus der Datenbank."""
    with lock:
        cursor.execute("SELECT * FROM watchdog_state ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return {
                "last_watchdog_time": row[1],
                "status": row[2],
                "total_received": row[3],
                "invalid_received": row[4],
            }
        else:
            return {
                "last_watchdog_time": 0,
                "status": "initializing",
                "total_received": 0,
                "invalid_received": 0,
            }


def update_watchdog_state(state):
    """Aktualisiert den Watchdog-Status in der Datenbank."""
    with lock:
        cursor.execute(
            """
            INSERT INTO watchdog_state (last_watchdog_time, status, total_received, invalid_received)
            VALUES (?, ?, ?, ?)
        """,
            (
                state["last_watchdog_time"],
                state["status"],
                state["total_received"],
                state["invalid_received"],
            ),
        )
        conn.commit()


def check_watchdog():
    """Überprüft regelmäßig den Status des Watchdogs und sendet eine Benachrichtigung, wenn keine neue Nachricht empfangen wurde."""
    while True:
        current_time = time.time()
        state = get_watchdog_state()
        time_since_last = current_time - state["last_watchdog_time"]

        # Überprüfe, ob die Zeit seit dem letzten Watchdog das Timeout überschreitet
        if time_since_last > watchdog_timeout:
            if state["status"] != "alert":
                state["status"] = "alert"
                last_received = format_timestamp(state["last_watchdog_time"])

                message = (
                    f"*(ERROR) Watchdog alert - Missing*\n"
                    f"Description: No Alertmanager Watchdog messages received in the last {int(time_since_last)} seconds.\n"
                    f"Last watchdog message was received at: {last_received}\n"
                    f"Summary: Alerting pipeline might be broken or Alertmanager unreachable"
                )
                send_google_chat_notification(message)
                update_watchdog_state(state)

        # Sendet regelmäßig einen Status, wenn alles okay ist (einmal am Tag)
        elif (
            state["status"] == "ok" and time_since_last % 86400 < 60
        ):  # ~einmal pro Tag
            message = (
                f"*(INFO) Watchdog status - OK*\n"
                f"Description: Alertmanager Watchdog messages are being received normally.\n"
                f"Last received: {format_timestamp(state['last_watchdog_time'])}\n"
                f"Summary: Alerting pipeline is functioning correctly"
            )
            send_google_chat_notification(message)

        # Verzögerung für die nächste Überprüfung (1/10 des Timeout-Werts, aber mindestens 30 Sekunden)
        sleep_time = max(30, int(watchdog_timeout / 10))
        time.sleep(sleep_time)


def validate_watchdog_alert(payload):
    """Überprüft, ob die empfangene Payload ein gültiger Watchdog-Alert ist."""
    try:
        # Prüfe, ob das Payload die erwartete Struktur hat
        if "alerts" not in payload:
            logger.warning("Received payload without 'alerts' key")
            return False

        alerts = payload["alerts"]
        if not alerts or not isinstance(alerts, list):
            logger.warning("Received empty or invalid 'alerts' array")
            return False

        # Suche nach einem Watchdog-Alert in der Liste
        for alert in alerts:
            if "labels" in alert and "alertname" in alert["labels"]:
                alertname = alert["labels"]["alertname"]
                status = alert.get("status", "unknown")

                if alertname == expected_alertname and status == "firing":
                    logger.info(
                        f"Valid Watchdog alert received: {alertname} (status: {status})"
                    )
                    return alert

        logger.warning("No valid Watchdog alert found in payload")
        logger.debug(f"Received payload: {json.dumps(payload)}")
        return False

    except Exception as e:
        logger.error(f"Error validating watchdog alert: {str(e)}")
        return False


@webapp.route("/watchdog", methods=["POST"])
def watchdog():
    """Empfängt POST-Anfragen von Alertmanager und verarbeitet die Watchdog-Alerts."""
    try:
        state = get_watchdog_state()

        # Zähler für Gesamtanfragen erhöhen
        state["total_received"] += 1

        # Die JSON-Payload abrufen
        payload = request.get_json(silent=True)
        if not payload:
            # Ungültiges JSON sollte auch als ungültige Anfrage gezählt werden
            state["invalid_received"] += 1
            logger.warning("Received empty or invalid JSON payload")
            update_watchdog_state(state)
            return jsonify({"status": "error", "message": "Invalid payload"}), 400

        # Payload für Debug-Zwecke loggen
        logger.debug(f"Received alert payload: {json.dumps(payload)}")

        # Überprüfen, ob es sich um einen gültigen Watchdog-Alert handelt
        valid_alert = validate_watchdog_alert(payload)
        if valid_alert:
            # Aktualisiere den Zeitstempel und den Status
            state["last_watchdog_time"] = time.time()

            # Wenn wir vorher im Alert-Status waren, sende eine Erholungsnachricht
            if state["status"] == "alert":
                message = (
                    "*(INFO) Watchdog recovered*\n"
                    "Description: Alertmanager Watchdog messages are being received again.\n"
                    "Summary: Alerting pipeline has recovered"
                )
                send_google_chat_notification(message)

            state["status"] = "ok"
            update_watchdog_state(state)
            return jsonify(
                {"status": "success", "message": "Valid watchdog alert processed"}
            ), 200
        else:
            # Es handelt sich nicht um einen gültigen Watchdog-Alert
            state["invalid_received"] += 1
            logger.warning(
                f"Received invalid watchdog alert. Total invalid: {state['invalid_received']}"
            )
            update_watchdog_state(state)
            return jsonify(
                {
                    "status": "warning",
                    "message": "Received alert is not a valid watchdog alert",
                }
            ), 200

    except Exception as e:
        # Auch Ausnahmen sollten als ungültige Anfragen gezählt werden
        state["invalid_received"] += 1
        logger.error(f"Error processing watchdog request: {str(e)}")
        update_watchdog_state(state)
        return jsonify({"status": "error", "message": str(e)}), 500


@webapp.route("/health", methods=["GET"])
def health_check():
    """Endpunkt für Health-Checks."""
    current_time = time.time()
    state = get_watchdog_state()
    time_since_last = current_time - state["last_watchdog_time"]

    health_status = {
        "status": state["status"],
        "last_watchdog_received": format_timestamp(state["last_watchdog_time"]),
        "seconds_since_last_watchdog": int(time_since_last),
        "timeout_threshold": watchdog_timeout,
        "is_healthy": time_since_last <= watchdog_timeout,
        "total_alerts_received": state["total_received"],
        "invalid_alerts_received": state["invalid_received"],
    }

    status_code = 200 if health_status["is_healthy"] else 503
    return jsonify(health_status), status_code


@webapp.route("/status", methods=["GET"])
def status():
    """Liefert detaillierte Statusinformationen."""
    current_time = time.time()
    state = get_watchdog_state()
    return jsonify(
        {
            "current_time": format_timestamp(current_time),
            "watchdog_state": state,
            "config": {
                "timeout": watchdog_timeout,
                "expected_alertname": expected_alertname,
                "has_webhook_url": google_chat_webhook_url is not None,
                "db_file": DB_FILE,
            },
            "uptime": int(current_time - start_time),
        }
    ), 200


@webapp.route("/", methods=["GET"])
def root():
    """Root-Endpunkt für einfache Verfügbarkeitsprüfung."""
    return jsonify(
        {
            "service": "Alertmanager Watchdog Service",
            "version": "1.0.0",
            "status": "running",
            "endpoints": [
                {
                    "path": "/watchdog",
                    "method": "POST",
                    "description": "Endpoint for Alertmanager webhook",
                },
                {
                    "path": "/health",
                    "method": "GET",
                    "description": "Health check endpoint",
                },
                {
                    "path": "/status",
                    "method": "GET",
                    "description": "Detailed status information",
                },
            ],
        }
    ), 200


@webapp.route("/cleanup", methods=["POST"])
def cleanup():
    """Bereinigt alte Einträge aus der Datenbank."""
    token = request.headers.get("Authorization")
    if token != f"Bearer {cleanup_token}":
        abort(403)  # Verboten, wenn das Token nicht korrekt ist

    now = datetime.now()
    cutoff_time = now - timedelta(days=30)  # Einträge älter als 30 Tage löschen
    cutoff_timestamp = cutoff_time.timestamp()

    with lock:
        cursor.execute(
            "DELETE FROM watchdog_state WHERE last_watchdog_time < ?",
            (cutoff_timestamp,),
        )
        conn.commit()
        logger.info(f"Deleted entries older than {cutoff_time}")

    return jsonify(
        {"status": "success", "message": f"Deleted entries older than {cutoff_time}"}
    ), 200


# Beim Starten der Anwendung: Lade den letzten Watchdog-Zeitstempel
start_time = time.time()
state = get_watchdog_state()
if state["status"] == "initializing":
    state["status"] = "waiting_for_first_alert"
    update_watchdog_state(state)

# Starte den Watchdog-Check Thread, wenn die Anwendung nicht von Gunicorn gestartet wird
if not os.environ.get("RUNNING_IN_GUNICORN", ""):
    checker_thread = Thread(target=check_watchdog, daemon=True)
    checker_thread.start()

# Wenn das Skript direkt ausgeführt wird (nicht als Modul importiert)
if __name__ == "__main__":
    logger.info(
        f"Starting Watchdog Service (timeout: {watchdog_timeout}s, expected alertname: {expected_alertname})"
    )

    # Flask-Webanwendung starten (nur für Entwicklung)
    webapp.run(host="0.0.0.0", port=5001, threaded=True)
