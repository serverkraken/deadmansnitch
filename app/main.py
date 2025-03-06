import time
import os
import requests
import json
from flask import Flask, jsonify
from threading import Thread

# Flask initialisieren
webapp = Flask(__name__)

# Dateipfad für die Persistenz
PERSISTENCE_FILE = "watchdog_state.json"

# Konfiguration aus Umgebungsvariablen laden
google_chat_webhook_url = os.getenv("GOOGLE_CHAT_WEBHOOK_URL")
watchdog_timeout = int(os.getenv("WATCHDOG_TIMEOUT", 60))  # Default auf 60 Sekunden


def load_watchdog_state():
    """Lädt den letzten Watchdog-Zeitstempel aus einer Datei."""
    if os.path.exists(PERSISTENCE_FILE):
        with open(PERSISTENCE_FILE, "r") as f:
            return json.load(f).get("last_watchdog_time", time.time())
    return time.time()  # Wenn keine Datei existiert, setze den Zeitstempel auf jetzt


def save_watchdog_state():
    """Speichert den aktuellen Watchdog-Zeitstempel in einer Datei."""
    with open(PERSISTENCE_FILE, "w") as f:
        json.dump({"last_watchdog_time": last_watchdog_time}, f)


# Beim Starten der Anwendung: Lade den letzten Watchdog-Zeitstempel
last_watchdog_time = load_watchdog_state()


def send_google_chat_notification(message):
    """Sendet eine Benachrichtigung an Google Chat."""
    if google_chat_webhook_url is None:
        raise ValueError("GOOGLE_CHAT_WEBHOOK_URL Umgebungsvariable ist nicht gesetzt.")

    headers = {"Content-Type": "application/json; charset=UTF-8"}
    data = {"text": message}
    response = requests.post(google_chat_webhook_url, headers=headers, json=data)

    if response.status_code == 200:
        print(f"Notification sent successfully: {message}")
    else:
        print(f"Failed to send notification. Status code: {response.status_code}")

    return response.status_code == 200


def check_watchdog():
    """Überprüft regelmäßig den Status des Watchdogs und sendet eine Benachrichtigung, wenn keine neue Nachricht empfangen wurde."""
    global last_watchdog_time
    while True:
        current_time = time.time()
        if current_time - last_watchdog_time > watchdog_timeout:
            send_google_chat_notification(
                f"*(ERROR) Watchdog alert - Firing*\nDescription: No messages received in the last {watchdog_timeout} seconds.\nSummary: Cluster might be in an Errored state or has no Internet Connectivity"
            )
            last_watchdog_time = (
                current_time  # Reset the time to avoid multiple notifications
            )
        time.sleep(watchdog_timeout)


@webapp.route("/watchdog", methods=["POST"])
def watchdog():
    """Empfängt POST-Anfragen und setzt den Zeitstempel für den Watchdog zurück."""
    global last_watchdog_time
    last_watchdog_time = time.time()
    try:
        save_watchdog_state()  # Speichere den neuen Zeitstempel
        print(f"Saved state to {PERSISTENCE_FILE}")
    except Exception as e:
        print(e)

    return jsonify({"status": "received"}), 200


if __name__ == "__main__":
    # Den Watchdog-Check in einem separaten Thread starten
    Thread(target=check_watchdog, daemon=True).start()

    # Flask-Webanwendung starten
    webapp.run(host="0.0.0.0", port=5001, threaded=True)
