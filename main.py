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
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        print(f"\nReceived signal {signum}, initiating graceful shutdown...")
        self.stop()
    
    def _setup_logging(self):
        """Setup logging based on configuration"""
        # Create logger
        self.logger = logging.getLogger('ServiceController')
        self.logger.setLevel(getattr(logging, self.config.logging.level.upper()))
        
        # Clear existing handlers
        self.logger.handlers.clear()
        
        # Setup file handler with rotation
        file_handler = RotatingFileHandler(
            self.config.logging.file_path,
            maxBytes=self.config.logging.max_file_size,
            backupCount=self.config.logging.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, self.config.logging.level.upper()))
        
        # Setup console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, self.config.logging.level.upper()))
        
        # Create formatter
        formatter = logging.Formatter(self.config.logging.format)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Set root logger level to prevent duplicate logs
        logging.getLogger().setLevel(getattr(logging, self.config.logging.level.upper()))
        
        self.logger.info("Logging configured successfully")
    
    def initialize(self) -> bool:
        """Initialize the service controller"""
        try:
            # Load environment variables
            load_dotenv()
            
            # Load configuration
            self.config = load_config(self.config_path)
            
            # Setup logging
            self._setup_logging()
            
            # Validate configuration
            from config.config_loader import config_loader
            if not config_loader.validate_config():
                self.logger.error("Configuration validation failed")
                return False
            
            # Test database connection
            self.logger.info("Testing database connection...")
            if not test_connection():
                self.logger.error("Database connection test failed")
                return False
            
            # Initialize service checker
            self.service_checker = ServiceChecker(self.config)
            
            self.logger.info("Service Controller initialized successfully")
            return True
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to initialize Service Controller: {e}")
            else:
                print(f"Failed to initialize Service Controller: {e}")
            return False
    
    def _discover_cluster(self) -> bool:
        """Discover and connect to the active cluster node"""
        self.logger.info(f"Discovering active node in cluster: {self.config.cluster.name}")
        
        active_node = self.service_checker.discover_active_node()
        if not active_node:
            self.logger.error("No active cluster node found")
            return False
        
        self.logger.info(f"Connected to active node: {active_node}")
        return True
    
    def _monitor_services(self):
        """Main monitoring loop running in a separate thread"""
        self.logger.info("Starting service monitoring loop...")
        
        while self.is_running:
            try:
                start_time = time.time()
                
                # Check cluster health first
                if not self.service_checker.is_cluster_healthy():
                    self.logger.error("Cluster is unhealthy, attempting to reconnect...")
                    if not self._discover_cluster():
                        self.logger.error("Failed to reconnect to cluster, waiting before retry...")
                        time.sleep(self.config.settings.check_interval)
                        continue
                
                # Check all services
                self.logger.info("Starting service checks...")
                results = self.service_checker.check_all_services()
                
                # Log summary
                total_services = len(results)
                successful_services = sum(1 for success in results.values() if success)
                failed_services = total_services - successful_services
                
                self.logger.info(f"Service check completed: {successful_services}/{total_services} successful")
                
                if failed_services > 0:
                    failed_list = [name for name, success in results.items() if not success]
                    self.logger.warning(f"Failed services: {', '.join(failed_list)}")
                
                # Calculate sleep time to maintain check interval
                elapsed_time = time.time() - start_time
                sleep_time = max(0, self.config.settings.check_interval - elapsed_time)
                
                if sleep_time > 0:
                    self.logger.debug(f"Sleeping for {sleep_time:.1f} seconds until next check")
                    time.sleep(sleep_time)
                else:
                    self.logger.warning(f"Service checks took {elapsed_time:.1f}s, longer than interval of {self.config.settings.check_interval}s")
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.config.settings.check_interval)
        
        self.logger.info("Service monitoring loop stopped")
    
    def start(self) -> bool:
        """Start the service controller"""
        if not self.initialize():
            return False
        
        try:
            self.logger.info("=" * 60)
            self.logger.info("VERACITY SERVICE CONTROLLER STARTING")
            self.logger.info("=" * 60)
            self.logger.info(f"Cluster: {self.config.cluster.name}")
            self.logger.info(f"Role: {self.config.cluster.role_name}")
            self.logger.info(f"Machine: {self.service_checker.machine_name}")
            self.logger.info(f"Services to monitor: {len(self.config.services)}")
            self.logger.info(f"Check interval: {self.config.settings.check_interval}s")
            
            # Discover cluster
            if not self._discover_cluster():
                self.logger.error("Failed to discover cluster, cannot start")
                return False
            
            # Start monitoring in separate thread
            self.is_running = True
            self.monitor_thread = threading.Thread(
                target=self._monitor_services,
                name="ServiceMonitor",
                daemon=True
            )
            self.monitor_thread.start()
            
            self.logger.info("Service Controller started successfully")
            
            # Main thread keeps running until stopped
            try:
                while self.is_running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.logger.info("Received keyboard interrupt")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start Service Controller: {e}")
            return False
    
    def stop(self):
        """Stop the service controller"""
        if not self.is_running:
            return
        
        self.logger.info("Stopping Service Controller...")
        self.is_running = False
        
        # Wait for monitor thread to finish
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.logger.info("Waiting for monitoring thread to stop...")
            self.monitor_thread.join(timeout=10)
            
            if self.monitor_thread.is_alive():
                self.logger.warning("Monitoring thread did not stop gracefully")
        
        self.logger.info("Service Controller stopped")
    
    def status(self) -> dict:
        """Get current status of the service controller"""
        if not self.service_checker:
            return {"status": "not_initialized"}
        
        try:
            # Get cluster status
            cluster_healthy = self.service_checker.is_cluster_healthy()
            
            # Get service statuses
            service_statuses = {}
            for service_config in self.config.services:
                status = self.service_checker.get_service_status(service_config.name)
                service_statuses[service_config.name] = status.value
            
            return {
                "status": "running" if self.is_running else "stopped",
                "cluster": {
                    "name": self.config.cluster.name,
                    "healthy": cluster_healthy,
                    "active_node": self.service_checker.current_active_node
                },
                "services": service_statuses,
                "machine": {
                    "name": self.service_checker.machine_name,
                    "ip": self.service_checker.machine_ip
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error getting status: {e}")
            return {"status": "error", "error": str(e)}
    
    def reload_config(self) -> bool:
        """Reload configuration without stopping the service"""
        try:
            self.logger.info("Reloading configuration...")
            
            # Load new configuration
            new_config = load_config(self.config_path)
            
            # Validate new configuration
            from config.config_loader import config_loader
            if not config_loader.validate_config():
                self.logger.error("New configuration validation failed")
                return False
            
            # Update configuration
            old_check_interval = self.config.settings.check_interval if self.config else 30
            self.config = new_config
            
            # Update service checker
            if self.service_checker:
                self.service_checker.config = self.config
            
            # Update logging if level changed
            if self.logger:
                self.logger.setLevel(getattr(logging, self.config.logging.level.upper()))
                for handler in self.logger.handlers:
                    handler.setLevel(getattr(logging, self.config.logging.level.upper()))
            
            self.logger.info("Configuration reloaded successfully")
            
            # Log if check interval changed
            new_check_interval = self.config.settings.check_interval
            if old_check_interval != new_check_interval:
                self.logger.info(f"Check interval changed from {old_check_interval}s to {new_check_interval}s")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {e}")
            return False


def create_default_config():
    """Create default configuration file if it doesn't exist"""
    if not os.path.exists("config.yaml"):
        print("Configuration file not found, creating default config.yaml...")
        from config.config_loader import ConfigLoader
        loader = ConfigLoader()
        loader.save_default_config("config.yaml")
        print("Default configuration created. Please edit config.yaml before running.")
        return False
    return True


def main():
    """Main entry point"""
    print("VERACITY Service Controller")
    print("=" * 40)
    
    # Check if config exists, create default if not
    if not create_default_config():
        return 1
    
    # Check command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "config":
            # Create/recreate default config
            from config.config_loader import ConfigLoader
            loader = ConfigLoader()
            loader.save_default_config("config.yaml")
            print("Default configuration saved to config.yaml")
            return 0
        
        elif command == "test":
            # Test configuration and connections
            controller = ServiceController()
            if controller.initialize():
                print("✓ Configuration valid")
                print("✓ Database connection successful")
                print("✓ Service Controller ready")
                return 0
            else:
                print("✗ Service Controller initialization failed")
                return 1
        
        elif command == "status":
            # Get status (if running)
            controller = ServiceController()
            if controller.initialize():
                status = controller.status()
                print("Current Status:")
                print(f"  Controller: {status.get('status', 'unknown')}")
                if 'cluster' in status:
                    print(f"  Cluster: {status['cluster']['name']} ({'healthy' if status['cluster']['healthy'] else 'unhealthy'})")
                    print(f"  Active Node: {status['cluster'].get('active_node', 'none')}")
                if 'services' in status:
                    print("  Services:")
                    for service, service_status in status['services'].items():
                        print(f"    {service}: {service_status}")
                return 0
            else:
                return 1
        
        else:
            print(f"Unknown command: {command}")
            print("Usage: python main.py [config|test|status]")
            return 1
    
    # Default: start service controller
    controller = ServiceController()
    
    try:
        success = controller.start()
        return 0 if success else 1
        
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1
    
    finally:
        controller.stop()


if __name__ == "__main__":
    sys.exit(main())