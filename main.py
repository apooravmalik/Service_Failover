import logging
import time
import signal
import sys
import os
from datetime import datetime
from typing import Optional
import threading
from logging.handlers import RotatingFileHandler

from config.config_loader import load_config, Config
from services.communication import MessageHandler
from services.service_checker import ServiceChecker
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
            
            # --- Heartbeat communication is no longer needed for failover ---
            # communication_port = getattr(self.config.settings, 'communication_port', 12345)
            # self.message_handler = MessageHandler(my_node.ip, communication_port, self.handle_incoming_message)
            
            self.logger.info("Service Controller initialized successfully")
            return True
            
        except Exception as e:
            (self.logger or logging).error(f"Failed to initialize Service Controller: {e}", exc_info=True)
            return False
    
    def handle_incoming_message(self, message):
        """Callback function to handle messages from the other node."""
        # This function is no longer critical but left for potential future use
        self.last_heartbeat_received = datetime.now()
        self.other_node_status = message
    
    def _monitor_services(self):
        """Main monitoring loop running in a separate thread"""
        self.logger.info("Starting service monitoring loop...")
        
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

        # This status is now for information/logging only, not for failover
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
        """
        my_node = self.service_checker.get_my_node()
        
        self.logger.debug("Getting cluster owner node...")
        definitive_owner = self.service_checker.get_cluster_owner_node()
        self.logger.debug(f"Finished getting cluster owner node. Owner: {definitive_owner}")

        # --- Primary Logic: Prioritize Windows Cluster ---
        if definitive_owner:
            self.logger.debug(f"Making decision based on Windows Cluster. Owner is '{definitive_owner}'.")
            if os.path.normcase(my_node.name) == os.path.normcase(definitive_owner):
                self.logger.info("This node is the Cluster Owner. Ensuring services are active.")
                self.handle_services_on_active_node()
            else:
                self.logger.info(f"This node is not the Cluster Owner ('{definitive_owner}'). Ensuring services are stopped.")
                self.service_checker.stop_all_services()
            return

        # --- No Fallback Logic ---
        self.logger.error("Could not determine Windows Cluster owner. Taking no action to prevent split-brain. Will retry.")
    
    def handle_services_on_active_node(self):
        """Ensure all services are running on the node that is currently active."""
        self.logger.info("Node is in active state. Checking and starting services as needed.")
        if not self.service_checker.check_viewscape_service_local():
            self.service_checker.start_service(self.config.viewscape.service_name)
        
        for service_config in self.config.services:
            self.service_checker.handle_service(service_config)
            
    def start(self) -> bool:
        """Start the service controller"""
        if not self.initialize(): return False
        
        self.logger.info("=" * 60)
        self.logger.info(f"VERACITY SERVICE CONTROLLER STARTING on {self.service_checker.machine_name}")
        self.logger.info(f"Services to monitor: {[s.name for s in self.config.services]}")
        
        # --- Heartbeat server is no longer needed ---
        # self.server_thread = threading.Thread(target=self.message_handler.start_server, daemon=True)
        # self.server_thread.start()
        
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_services, daemon=True)
        self.monitor_thread.start()
        
        self.logger.info("Service Controller started successfully")
        
        try:
            while self.is_running: time.sleep(1)
        except KeyboardInterrupt: self.logger.info("Keyboard interrupt received.")
        return True
    
    def stop(self):
        """Stop the service controller"""
        if not self.is_running: return
        self.is_running = False
        # if self.message_handler: self.message_handler.stop_server()
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