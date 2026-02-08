import json
import logging
import time
from typing import Optional, Tuple

from flask import Blueprint, Response, jsonify, request

from app.services.kubernetes_probes import KubernetesProbes
from app.services.watchdog_service import WatchdogService

bp = Blueprint("routes", __name__)
logger = logging.getLogger("watchdog_service")

# We'll inject the service in __init__.py
watchdog_service: Optional[WatchdogService] = None
kubernetes_probes: Optional[KubernetesProbes] = None


def init_routes(service: WatchdogService) -> Blueprint:
    global watchdog_service, kubernetes_probes
    watchdog_service = service
    kubernetes_probes = KubernetesProbes(service)
    return bp


@bp.route("/watchdog", methods=["POST"])
def watchdog() -> Tuple[Response, int]:
    """Endpoint for Alertmanager webhook"""
    try:
        # Get JSON payload
        payload = request.get_json(silent=True)

        # Log the payload for debugging
        logger.debug(f"Received alert payload: {json.dumps(payload) if payload else 'None'}")

        # Process the alert
        if watchdog_service is None:
             return jsonify({"status": "error", "message": "Service not initialized"}), 500

        success, message = watchdog_service.process_watchdog_alert(payload)

        if not success and payload is None:
            return jsonify({"status": "error", "message": message}), 400

        return jsonify({"status": "success" if success else "warning", "message": message}), 200

    except Exception as e:
        logger.error(f"Error processing watchdog request: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/health", methods=["GET"])
def health_check() -> Tuple[Response, int]:
    """Health check endpoint"""
    if watchdog_service is None:
         return jsonify({"status": "error", "message": "Service not initialized"}), 500

    health_status = watchdog_service.get_health_status()

    # Consider healthy if explicitly healthy OR in startup phase
    is_healthy = health_status["is_healthy"] or health_status["status"] in ["initializing", "waiting_for_first_alert"]

    status_code = 200 if is_healthy else 503
    return jsonify(health_status), status_code


@bp.route("/probe/liveness", methods=["GET"])
def liveness_probe() -> Tuple[Response, int]:
    """Kubernetes liveness probe endpoint"""
    if kubernetes_probes is None:
         return jsonify({"status": "error", "message": "Probes not initialized"}), 500

    is_alive, message = kubernetes_probes.check_liveness()
    status_code = 200 if is_alive else 503
    return jsonify(
        {
            "status": "alive" if is_alive else "dead",
            "message": message,
            "timestamp": time.time(),
        }
    ), status_code


@bp.route("/probe/readiness", methods=["GET"])
def readiness_probe() -> Tuple[Response, int]:
    """Kubernetes readiness probe endpoint"""
    if kubernetes_probes is None:
         return jsonify({"status": "error", "message": "Probes not initialized"}), 500

    is_ready, message = kubernetes_probes.check_readiness()
    status_code = 200 if is_ready else 503
    return jsonify(
        {
            "status": "ready" if is_ready else "not_ready",
            "message": message,
            "timestamp": time.time(),
        }
    ), status_code


@bp.route("/status", methods=["GET"])
def status() -> Tuple[Response, int]:
    """Detailed status endpoint"""
    if watchdog_service is None:
         return jsonify({"status": "error", "message": "Service not initialized"}), 500

    detailed_status = watchdog_service.get_detailed_status()
    return jsonify(detailed_status), 200


@bp.route("/", methods=["GET"])
def root() -> Tuple[Response, int]:
    """Root endpoint for service information"""
    return jsonify(
        {
            "service": "Alertmanager Watchdog Service",
            "version": "2.0.0",
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
                {
                    "path": "/probe/liveness",
                    "method": "GET",
                    "description": "Kubernetes liveness probe endpoint",
                },
                {
                    "path": "/probe/readiness",
                    "method": "GET",
                    "description": "Kubernetes readiness probe endpoint",
                },
            ],
        }
    ), 200
