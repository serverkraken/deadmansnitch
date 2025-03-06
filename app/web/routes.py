from flask import request, jsonify, Blueprint
import json
import logging

bp = Blueprint('routes', __name__)
logger = logging.getLogger("watchdog_service")

# We'll inject the service in __init__.py
watchdog_service = None

def init_routes(service):
    global watchdog_service
    watchdog_service = service
    return bp

@bp.route("/watchdog", methods=["POST"])
def watchdog():
    """Endpoint for Alertmanager webhook"""
    try:
        # Get JSON payload
        payload = request.get_json(silent=True)
        
        # Log the payload for debugging
        logger.debug(f"Received alert payload: {json.dumps(payload) if payload else 'None'}")
        
        # Process the alert
        success, message = watchdog_service.process_watchdog_alert(payload)
        
        if not success and payload is None:
            return jsonify({"status": "error", "message": message}), 400
            
        return jsonify({"status": "success" if success else "warning", "message": message}), 200
        
    except Exception as e:
        logger.error(f"Error processing watchdog request: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    health_status = watchdog_service.get_health_status()
    status_code = 200 if health_status["is_healthy"] else 503
    return jsonify(health_status), status_code

@bp.route("/status", methods=["GET"])
def status():
    """Detailed status endpoint"""
    detailed_status = watchdog_service.get_detailed_status()
    return jsonify(detailed_status), 200

@bp.route("/", methods=["GET"])
def root():
    """Root endpoint for service information"""
    return jsonify({
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
        ],
    }), 200