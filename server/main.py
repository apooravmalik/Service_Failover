import logging
import time
import signal
import sys
import os
from datetime import datetime
from typing import Optional
import threading
from logging.handlers import RotatingFileHandler
from api import app as api_app, set_service_controller
from config.config_loader import load_config, Config
from services.communication import MessageHandler
from services.service_checker import ServiceChecker, CheckResult
from db.database import test_connection
from dotenv import load_dotenv

class ServiceController:
    """Main service controller orchestrator"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config: Optional[Config] = None
        self.service_checker: Optional[ServiceChecker] = None
        self.is_running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.logger: Optional[logging.Logger] = None
        self.message_handler: Optional[MessageHandler] = None
        self.other_node_status = {}
        self.last_heartbeat_received = None
        self.last_known_owner: Optional[str] = None
        self.ptz_consecutive_failures = 0
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        print(f"\nReceived signal {signum}, initiating graceful shutdown...")
        self.stop()
    
    def _setup_logging(self):
        """Setup logging based on configuration"""
        self.logger = logging.getLogger('ServiceController')
        self.logger.setLevel(getattr(logging, self.config.logging.level.upper()))
        self.logger.handlers.clear()
        
        file_handler = RotatingFileHandler(
            self.config.logging.file_path,
            maxBytes=self.config.logging.max_file_size,
            backupCount=self.config.logging.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, self.config.logging.level.upper()))
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, self.config.logging.level.upper()))
        
        formatter = logging.Formatter(self.config.logging.format)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        logging.getLogger().setLevel(getattr(logging, self.config.logging.level.upper()))
        self.logger.info("Logging configured successfully")
    
    def initialize(self) -> bool:
        """Initialize the service controller"""
        try:
            load_dotenv()
            self.config = load_config(self.config_path)
            self._setup_logging()
            
            from config.config_loader import config_loader
            if not config_loader.validate_config():
                self.logger.error("Configuration validation failed")
                return False
            
            self.logger.info("Testing database connection...")
            if not test_connection():
                self.logger.error("Database connection test failed")
                return False
            
            self.service_checker = ServiceChecker(self.config)
            my_node = self.service_checker.get_my_node()
            if not my_node:
                self.logger.error("Could not determine the current node from config.")
                return False
            
            self.logger.info("Service Controller initialized successfully")
            return True
            
        except Exception as e:
            (self.logger or logging).error(f"Failed to initialize Service Controller: {e}", exc_info=True)
            return False
    
    def handle_incoming_message(self, message):
        """Callback function to handle messages from the other node."""
        self.last_heartbeat_received = datetime.now()
        self.other_node_status = message
    
    def _monitor_services(self):
        """Main monitoring loop running in a separate thread"""
        self.logger.info("Starting service monitoring loop...")
        
        self.service_checker.check_initial_db_ip()

        while self.is_running:
            try:
                self.logger.debug("--- Monitor loop started ---")
                start_time = time.time()

                self.logger.debug("Making failover decision...")
                self.make_failover_decision()
                self.logger.debug("Finished making failover decision.")

                elapsed_time = time.time() - start_time
                sleep_time = max(0, self.config.settings.check_interval - elapsed_time)
                self.logger.debug(f"Loop took {elapsed_time:.2f}s. Sleeping for {sleep_time:.2f}s.")

                if sleep_time > 0:
                    time.sleep(sleep_time)
                self.logger.debug("--- Monitor loop finished ---")
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                time.sleep(self.config.settings.check_interval)
        
        self.logger.info("Service monitoring loop stopped")
        
    def get_my_status(self) -> dict:
        """Get the current status of this machine, including cluster info."""
        self.logger.debug("Getting cluster owner node...")
        cluster_owner = self.service_checker.get_cluster_owner_node()
        self.logger.debug(f"Finished getting cluster owner node. Owner: {cluster_owner}")
        
        my_node_name = self.service_checker.get_my_node().name
        is_cluster_owner = (cluster_owner is not None and os.path.normcase(cluster_owner) == os.path.normcase(my_node_name))

        is_master_running = self.service_checker.check_viewscape_service_local()
        service_statuses = {
            s.name: self.service_checker.get_service_status(s.name).value
            for s in self.config.services
        }

        return {
            "node": my_node_name,
            "timestamp": datetime.now().isoformat(),
            "is_master_running": is_master_running,
            "services": service_statuses,
            "cluster_owner": cluster_owner,
            "is_cluster_owner": is_cluster_owner
        }
        
    def make_failover_decision(self):
        """
        Failover logic that relies ONLY on the Windows Cluster Owner.
        Triggers database updates only on owner change.
        """
        my_node = self.service_checker.get_my_node()
        
        self.logger.debug("Getting cluster owner node...")
        definitive_owner = self.service_checker.get_cluster_owner_node()
        self.logger.debug(f"Finished getting cluster owner node. Owner: {definitive_owner}")

        if definitive_owner and definitive_owner != self.last_known_owner:
            self.logger.info(f"Cluster owner has changed from '{self.last_known_owner}' to '{definitive_owner}'.")
            if os.path.normcase(my_node.name) == os.path.normcase(definitive_owner):
                self.logger.info("This node is the new owner. Updating database settings.")
                self.service_checker.update_database_for_all_services()
            self.last_known_owner = definitive_owner

        if definitive_owner:
            self.logger.debug(f"Making decision based on Windows Cluster. Owner is '{definitive_owner}'.")
            if os.path.normcase(my_node.name) == os.path.normcase(definitive_owner):
                self.logger.info("This node is the Cluster Owner. Ensuring services are active.")
                self.handle_services_on_active_node()
            else:
                self.logger.info(f"This node is not the Cluster Owner ('{definitive_owner}'). Ensuring services are stopped.")
                self.service_checker.stop_all_services()
            return

        self.logger.error("Could not determine Windows Cluster owner. Taking no action to prevent split-brain. Will retry.")
    
    def handle_services_on_active_node(self):
        """
        Handle the new service check logic: PTZ first, then escalate to Viewscape if PTZ fails repeatedly.
        """
        self.logger.info("Node is in active state. Checking services with new tiered logic.")

        # 1. Ensure ViewscapeMasterControl is running, but don't restart it yet based on PTZ.
        if not self.service_checker.check_viewscape_service_local():
            self.logger.warning(f"{self.config.viewscape.service_name} is stopped. Starting it now.")
            self.service_checker.start_service(self.config.viewscape.service_name)
        
        # 2. Find and prioritize the Veracity_PTZ service check.
        ptz_service_config = next((s for s in self.config.services if s.name == "Veracity_PTZ"), None)
        
        if not ptz_service_config:
            self.logger.error("Configuration error: 'Veracity_PTZ' not found in services list.")
            return

        ptz_check_result = self.service_checker.handle_service(ptz_service_config)

        # 3. Implement the new tiered restart logic.
        if ptz_check_result == CheckResult.FAILED:
            self.ptz_consecutive_failures += 1
            self.logger.warning(f"PTZ service check failed. Consecutive failures: {self.ptz_consecutive_failures}")

            # If it fails more than once, restart the master controller.
            if self.ptz_consecutive_failures > 1:
                self.logger.error(f"PTZ service has failed repeatedly. Escalating: Restarting {self.config.viewscape.service_name}.")
                self.service_checker.restart_service(self.config.viewscape.service_name)
                self.ptz_consecutive_failures = 0  # Reset counter after escalation
        
        elif ptz_check_result == CheckResult.PASSED:
            if self.ptz_consecutive_failures > 0:
                self.logger.info("PTZ service check has passed. Resetting consecutive failure counter.")
            self.ptz_consecutive_failures = 0  # Reset counter on success

        # 4. Handle any other configured services normally.
        for service_config in self.config.services:
            if service_config.name != "Veracity_PTZ":
                self.service_checker.handle_service(service_config)
            
    def start(self) -> bool:
        """Start the service controller"""
        if not self.initialize(): return False
        
        self.logger.info("=" * 60)
        self.logger.info(f"VERACITY SERVICE CONTROLLER STARTING on {self.service_checker.machine_name}")
        self.logger.info(f"Services to monitor: {[s.name for s in self.config.services]}")
        
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_services, daemon=True)
        self.monitor_thread.start()
        
        self.logger.info("Service Controller started successfully")
        
        # Determines the correct port for this specific machine from the config
        my_node_config = self.service_checker.get_my_node()
        if not my_node_config:
            self.logger.error("Could not determine API port for this node. API will not start.")
        else:
            api_port = my_node_config.port
            # Gives the API module access to this controller's instance
            set_service_controller(self) 
            # Starts the Flask server in a non-blocking background thread
            api_thread = threading.Thread(
                target=lambda: api_app.run(host='0.0.0.0', port=api_port, debug=False, use_reloader=False),
                daemon=True
            )
            api_thread.start()
            self.logger.info(f"GUI API server started on port {api_port}")
        
        try:
            while self.is_running: time.sleep(1)
        except KeyboardInterrupt: self.logger.info("Keyboard interrupt received.")
        return True
    
    def stop(self):
        """Stop the service controller"""
        if not self.is_running: return
        self.is_running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        self.logger.info("Service Controller stopped.")

def main():
    """Main entry point"""
    controller = ServiceController()
    try:
        if not controller.start():
            return 1
    except Exception as e:
        (controller.logger or logging).error(f"A fatal error occurred: {e}", exc_info=True)
        return 1
    finally:
        controller.stop()
    return 0

if __name__ == "__main__":
    sys.exit(main())