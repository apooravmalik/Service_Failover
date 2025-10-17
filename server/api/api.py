from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# This global variable will hold the instance of the main ServiceController.
service_controller = None

def set_service_controller(controller):
    """
    Allows the main.py to pass the running ServiceController instance
    to the API module.
    """
    global service_controller
    service_controller = controller

@app.route('/api/config', methods=['GET'])
def get_config():
    """
    Provides the frontend with the necessary configuration to discover and
    connect to all nodes in the cluster.
    """
    if service_controller and hasattr(service_controller, 'config'):
        # Fetches the node list from the loaded configuration object
        nodes = service_controller.config.cluster.nodes
        # Dynamically constructs the API URL for each node
        nodes_dict = [
            {"name": n.name, "url": f"http://{n.ip}:{n.port}/api/services"} for n in nodes
        ]
        return jsonify({"nodes": nodes_dict})
    return jsonify({"error": "Config not loaded"}), 500

@app.route('/api/services', methods=['GET'])
def get_services():
    """
    Provides the live status of all services specified in the 'services_GUI'
    section of the config.yaml for the local machine.
    """
    if service_controller and hasattr(service_controller, 'service_checker'):
        # Reads the list of services to display from the services_GUI config
        gui_services = service_controller.config.services_GUI
        service_statuses = []
        for service_config in gui_services:
            service_name = service_config.name
            # Uses the service_checker to get the current status of the service
            status = service_controller.service_checker.get_service_status(service_name)
            
            service_statuses.append({
                "name": service_name,
                "display_name": service_name,
                "status": status.value if status else "unknown",
                "instruction": service_config.instruction
            })
            
        return jsonify(service_statuses)
    return jsonify({"error": "Service controller not initialized"}), 500