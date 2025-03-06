import time
import os
import requests
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from threading import Thread

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("watchdog_service")

# Flask initialisieren
webapp = Flask(__name__)

# Dateipfad für die Persistenz
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
PERSISTENCE_FILE = os.path.join(DATA_DIR, "watchdog_state.json")

# Konfiguration aus Umgebungsvariablen laden
google_chat_webhook_url = os.getenv("GOOGLE_CHAT_WEBHOOK_URL")
watchdog_timeout = int(os.getenv("WATCHDOG_TIMEOUT", 3600))  # Default auf 1 Stunde
expected_alertname = os.getenv("EXPECTED_ALERTNAME", "Watchdog")

# Status-Variables für den Watchdog
watchdog_state = {
    "last_watchdog_time": 0,
    "last_watchdog_details": {},
    "status": "initializing",
    "total_received": 0,
    "invalid_received": 0,
}


def ensure_data_directory():
    """Stellt sicher, dass das Datenverzeichnis existiert"""
    if not os.path.exists(DATA_DIR):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            logger.info(f"Created data directory at {DATA_DIR}")
        except Exception as e:
            logger.error(f"Failed to create data directory: {e}")


def load_watchdog_state():
    """Lädt den Watchdog-Status aus einer Datei."""
    global watchdog_state
    ensure_data_directory()
    if os.path.exists(PERSISTENCE_FILE):
        try:
            with open(PERSISTENCE_FILE, "r") as f:
                saved_state = json.load(f)
                # Nur bekannte Werte übernehmen
                for key in watchdog_state.keys():
                    if key in saved_state:
                        watchdog_state[key] = saved_state[key]
            logger.info(
                f"Loaded watchdog state: Last alert received at {format_timestamp(watchdog_state['last_watchdog_time'])}"
            )
        except Exception as e:
            logger.error(f"Error loading watchdog state: {e}")
            watchdog_state["last_watchdog_time"] = time.time()  # Fallback
    else:
        watchdog_state["last_watchdog_time"] = (
            time.time()
        )  # Wenn keine Datei existiert, setze den Zeitstempel auf jetzt
        watchdog_state["status"] = "waiting_for_first_alert"
        save_watchdog_state()


def save_watchdog_state():
    """Speichert den aktuellen Watchdog-Status in einer Datei."""
    ensure_data_directory()
    try:
        with open(PERSISTENCE_FILE, "w") as f:
            json.dump(watchdog_state, f)
        logger.debug(f"Saved watchdog state to {PERSISTENCE_FILE}")
    except Exception as e:
        logger.error(f"Error saving watchdog state: {e}")


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


def check_watchdog():
    """Überprüft regelmäßig den Status des Watchdogs und sendet eine Benachrichtigung, wenn keine neue Nachricht empfangen wurde."""
    global watchdog_state

    # Variable für das tägliche Status-Update hinzufügen
    last_status_notification = time.time()

    while True:
        current_time = time.time()
        time_since_last = current_time - watchdog_state["last_watchdog_time"]
        time_since_last_notification = current_time - last_status_notification

        # Überprüfe, ob die Zeit seit dem letzten Watchdog das Timeout überschreitet
        if time_since_last > watchdog_timeout:
            if watchdog_state["status"] != "alert":
                watchdog_state["status"] = "alert"
                last_received = format_timestamp(watchdog_state["last_watchdog_time"])

                message = (
                    f"*(ERROR) Watchdog alert - Missing*\n"
                    f"Description: No Alertmanager Watchdog messages received in the last {int(time_since_last)} seconds.\n"
                    f"Last watchdog message was received at: {last_received}\n"
                    f"Summary: Alerting pipeline might be broken or Alertmanager unreachable"
                )
                send_google_chat_notification(message)
                save_watchdog_state()

        # Sendet regelmäßig einen Status, wenn alles okay ist (einmal am Tag)
        elif (
            watchdog_state["status"] == "ok" and time_since_last_notification >= 86400
        ):  # Wirklich nur einmal pro Tag
            message = (
                f"*(INFO) Watchdog status - OK*\n"
                f"Description: Alertmanager Watchdog messages are being received normally.\n"
                f"Last received: {format_timestamp(watchdog_state['last_watchdog_time'])}\n"
                f"Summary: Alerting pipeline is functioning correctly"
            )
            send_google_chat_notification(message)
            last_status_notification = (
                current_time  # Zeit der letzten Benachrichtigung aktualisieren
            )

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
    global watchdog_state

    try:
        # Zähler für Gesamtanfragen erhöhen
        watchdog_state["total_received"] += 1

        # Die JSON-Payload abrufen
        payload = request.get_json(silent=True)
        if not payload:
            # Ungültiges JSON sollte auch als ungültige Anfrage gezählt werden
            watchdog_state["invalid_received"] += 1
            logger.warning("Received empty or invalid JSON payload")
            return jsonify({"status": "error", "message": "Invalid payload"}), 400

        # Payload für Debug-Zwecke loggen
        logger.debug(f"Received alert payload: {json.dumps(payload)}")

        # Überprüfen, ob es sich um einen gültigen Watchdog-Alert handelt
        valid_alert = validate_watchdog_alert(payload)
        if valid_alert:
            # Aktualisiere den Zeitstempel und den Status
            watchdog_state["last_watchdog_time"] = time.time()
            watchdog_state["last_watchdog_details"] = {
                "alertname": valid_alert["labels"].get("alertname", "unknown"),
                "status": valid_alert.get("status", "unknown"),
                "summary": valid_alert.get("annotations", {}).get(
                    "summary", "No summary provided"
                ),
                "description": valid_alert.get("annotations", {}).get(
                    "description", "No description provided"
                ),
                "received_at": format_timestamp(time.time()),
            }

            # Wenn wir vorher im Alert-Status waren, sende eine Erholungsnachricht
            if watchdog_state["status"] == "alert":
                message = (
                    "*(INFO) Watchdog recovered*\n"
                    "Description: Alertmanager Watchdog messages are being received again.\n"
                    "Summary: Alerting pipeline has recovered"
                )
                send_google_chat_notification(message)

            watchdog_state["status"] = "ok"
            save_watchdog_state()
            return (
                jsonify(
                    {"status": "success", "message": "Valid watchdog alert processed"}
                ),
                200,
            )
        else:
            # Es handelt sich nicht um einen gültigen Watchdog-Alert
            watchdog_state["invalid_received"] += 1
            logger.warning(
                f"Received invalid watchdog alert. Total invalid: {watchdog_state['invalid_received']}"
            )
            return (
                jsonify(
                    {
                        "status": "warning",
                        "message": "Received alert is not a valid watchdog alert",
                    }
                ),
                200,
            )

    except Exception as e:
        # Auch Ausnahmen sollten als ungültige Anfragen gezählt werden
        watchdog_state["invalid_received"] += 1
        logger.error(f"Error processing watchdog request: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@webapp.route("/health", methods=["GET"])
def health_check():
    """Endpunkt für Health-Checks."""
    current_time = time.time()
    time_since_last = current_time - watchdog_state["last_watchdog_time"]

    health_status = {
        "status": watchdog_state["status"],
        "last_watchdog_received": format_timestamp(
            watchdog_state["last_watchdog_time"]
        ),
        "seconds_since_last_watchdog": int(time_since_last),
        "timeout_threshold": watchdog_timeout,
        "is_healthy": time_since_last <= watchdog_timeout,
        "total_alerts_received": watchdog_state["total_received"],
        "invalid_alerts_received": watchdog_state["invalid_received"],
    }

    status_code = 200 if health_status["is_healthy"] else 503
    return jsonify(health_status), status_code


@webapp.route("/status", methods=["GET"])
def status():
    """Liefert detaillierte Statusinformationen."""
    current_time = time.time()
    return (
        jsonify(
            {
                "current_time": format_timestamp(current_time),
                "watchdog_state": watchdog_state,
                "config": {
                    "timeout": watchdog_timeout,
                    "expected_alertname": expected_alertname,
                    "has_webhook_url": google_chat_webhook_url is not None,
                    "data_directory": DATA_DIR,
                    "persistence_file": PERSISTENCE_FILE,
                },
                "uptime": int(current_time - start_time),
            }
        ),
        200,
    )


@webapp.route("/", methods=["GET"])
def root():
    """Root-Endpunkt für einfache Verfügbarkeitsprüfung."""
    return (
        jsonify(
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
        ),
        200,
    )


# Beim Starten der Anwendung: Lade den letzten Watchdog-Zeitstempel
start_time = time.time()
load_watchdog_state()

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
