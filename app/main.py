import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Konfiguration
google_chat_webhook_url = "YOUR_GOOGLE_CHAT_WEBHOOK_URL"
watchdog_timeout = 60  # Zeit in Sekunden, nach der eine Benachrichtigung gesendet wird, wenn keine Nachrichten kommen

last_watchdog_time = time.time()


def send_google_chat_notification(message):
    headers = {"Content-Type": "application/json; charset=UTF-8"}
    data = {"text": message}
    response = requests.post(google_chat_webhook_url, headers=headers, json=data)
    return response.status_code == 200


@app.route("/watchdog", methods=["POST"])
def watchdog():
    global last_watchdog_time
    last_watchdog_time = time.time()
    return jsonify({"status": "received"}), 200


def check_watchdog():
    global last_watchdog_time
    while True:
        current_time = time.time()
        if current_time - last_watchdog_time > watchdog_timeout:
            send_google_chat_notification(
                "Watchdog alert: No messages received in the last {} seconds".format(
                    watchdog_timeout
                )
            )
            last_watchdog_time = (
                current_time  # Reset the time to avoid multiple notifications
            )
        time.sleep(watchdog_timeout)


if __name__ == "__main__":
    from threading import Thread

    Thread(target=check_watchdog).start()
    app.run(host="0.0.0.0", port=5000)
