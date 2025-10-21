import logging
import time
import signal
import sys
import os
from datetime import datetime
from typing import Optional
import threading
from logging.handlers import RotatingFileHandler

from config.config_loader import Config, ConfigLoader
# --- COMMENTED OUT --- The failover components are no longer needed for this
# from services.communication import MessageHandler 
# from services.service_checker import ServiceChecker, CheckResult
# --- We still need ServiceChecker for the API ---
from services.service_checker import ServiceChecker
# from db.database import test_connection
# from dotenv import load_dotenv
# Import the Flask app instance and the function to set the controller
from api import app as api_app, set_service_controller

class ServiceController:
    """Main service controller that orchestrates all operations."""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_loader = ConfigLoader(config_path)
        self.config: Optional[Config] = None
        self.service_checker: Optional[ServiceChecker] = None
        self.is_running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.logger = logging.getLogger(__name__)
        # self.message_handler: Optional[MessageHandler] = None
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handles shutdown signals like CTRL+C gracefully."""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.stop()
    
    def _setup_logging(self):
        """Configures the application logging based on the config file."""
        log_conf = self.config.logging
        
        # Use logging.getLogger() without a name to configure the root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(log_conf.level.upper())
        root_logger.handlers.clear()
        
        # File handler
        file_handler = RotatingFileHandler(
            log_conf.file_path,
            maxBytes=log_conf.max_file_size,
            backupCount=log_conf.backup_count,
            encoding='utf-8'
        )
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        
        formatter = logging.Formatter(log_conf.format)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        # Propagate logger settings to the class logger
        self.logger = logging.getLogger(__name__)
        self.logger.info("Logging configured successfully.")

    def initialize(self) -> bool:
        """Loads configuration and initializes all components."""
        try:
            # 1. load_dotenv() is REMOVED.
            
            # 2. This loads config, launches GUI, decrypts, and
            #    parses everything (including 'env') into the dataclass
            self.config = self.config_loader.load_config()
            
            # 3. Setup logging
            self._setup_logging()
            
            # 4. Validate
            if not self.config_loader.validate_config():
                self.logger.error("Configuration validation failed. Exiting.")
                return False
            
            # --- THIS IS THE NEW TEST FLOW ---
            # 5. Import db module and initialize with decrypted config
            try:
                from db import database # Import the module
                
                # 5a. Call with the specific 'env' part of the config
                if not database.init_db_engine(self.config.env):
                    self.logger.error("Failed to initialize database engine. Check credentials in GUI.")
                    return False
                    
                # 5b. Now, test the connection
                self.logger.info("Testing database connection...")
                if not database.test_connection():
                    self.logger.error("Database connection test failed. Decrypted credentials may be wrong.")
                    self.logger.warning("Continuing without database connection for API-only mode.")
                else:
                    self.logger.info("Database connection successful. Decrypted credentials are correct!")
                    
            except Exception as e:
                self.logger.error(f"Database module failed to load or connect: {e}")
                return False
            # --- END OF TEST FLOW ---

            # 6. Continue startup
            self.service_checker = ServiceChecker(self.config)
            self.logger.info("Service Controller initialized successfully.")
            return True
            
        except Exception as e:
            print(f"Failed to initialize Service Controller: {e}", file=sys.stderr)
            logging.error(f"Failed to initialize Service Controller: {e}", exc_info=True)
            return False
    # -----------------------------------

    def _monitor_services(self):
        """The main monitoring loop (COMMENTED OUT)."""
        self.logger.info("Monitoring loop started (but is disabled).")
        # while self.is_running:
        #     try:
        #         self.logger.debug("Performing service checks...")
        #         time.sleep(self.config.settings.check_interval)
        #     except Exception as e:
        #         self.logger.error(f"Error in monitoring loop: {e}", exc_info=True)
        #         time.sleep(self.config.settings.check_interval)
        self.logger.info("Service monitoring loop stopped.")

    def start(self) -> bool:
        """Starts all components of the service controller."""
        if not self.initialize():
            return False
        
        self.logger.info("=" * 60)
        self.logger.info(f"VERACITY SERVICE CONTROLLER STARTING in API-ONLY mode on {os.environ.get('COMPUTERNAME', 'Unknown')}")
        
        my_node_config = self.service_checker.get_my_node()
        if not my_node_config:
            self.logger.error("Could not determine API port for this node. API will not start.")
        else:
            api_port = my_node_config.port
            set_service_controller(self) 
            api_thread = threading.Thread(
                target=lambda: api_app.run(host='0.0.0.0', port=api_port, debug=False, use_reloader=False),
                daemon=True
            )
            api_thread.start()
            self.logger.info(f"GUI API server started on port {api_port}")
        
        self.is_running = True
        
        # self.monitor_thread = threading.Thread(target=self._monitor_services, daemon=True)
        # self.monitor_thread.start()
        self.logger.info("Failover monitoring thread is DISABLED.")
        
        self.logger.info("Service Controller started successfully.")
        
        try:
            # This loop is still needed to keep the main thread alive.
            # Without it, the program would exit, and the API (daemon thread) would shut down.
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received.")
        
        return True

    def stop(self):
        """Stops the service controller and cleans up resources."""
        if not self.is_running:
            return
        self.is_running = False
        # if self.monitor_thread and self.monitor_thread.is_alive():
        #     self.monitor_thread.join(timeout=5)
        self.logger.info("Service Controller stopped.")

def main():
    """Main entry point for the application."""
    controller = ServiceController()
    try:
        if not controller.start():
            return 1
    except Exception as e:
        logging.error(f"A fatal error occurred: {e}", exc_info=True)
        return 1
    finally:
        controller.stop()
    return 0

if __name__ == "__main__":
    sys.exit(main())