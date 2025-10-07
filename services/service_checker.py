import socket
import time
import subprocess
import os
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from datetime import datetime
from sqlalchemy import text
from config.config_loader import Config, ServiceConfig, LogCheck, get_config
from db.database import get_db, engine

logger = logging.getLogger(__name__)

class ServiceStatus(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    UNKNOWN = "unknown"
    STARTING = "starting"
    STOPPING = "stopping"

class CheckResult(Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"

class ServiceChecker:
    """Main service checking and management class"""
    
    def __init__(self, config: Config):
        self.config = config
        self.current_active_node = None
        self.machine_name = self._get_machine_name()
        self.machine_ip = self._get_machine_ip()
        
    def _get_machine_name(self) -> str:
        """Get the current machine name"""
        import platform
        return platform.node()
    
    def _get_machine_ip(self) -> str:
        """Get the current machine IP"""
        for node in self.config.cluster.nodes:
            # Use os.path.normcase for case-insensitive comparison robust on Windows
            if os.path.normcase(node.name) == os.path.normcase(self.machine_name):
                return node.ip
        # Fallback if no match is found (should not happen with correct config)
        return self.config.cluster.nodes[0].ip


    def get_other_node(self):
        """Get the config for the other machine in the cluster."""
        for node in self.config.cluster.nodes:
            if node.ip != self.machine_ip:
                return node
        return None
    
    def get_my_node(self):
        """Get the config object for the current machine."""
        for node in self.config.cluster.nodes:
            if node.ip == self.machine_ip:
                return node
        return None

    def check_viewscape_service_local(self) -> bool:
        """Check if the Viewscape service is running on the local machine."""
        status = self.get_service_status(self.config.viewscape.service_name)
        return status == ServiceStatus.RUNNING

    def get_service_status(self, service_name: str) -> ServiceStatus:
        """Get the status of a Windows service"""
        try:
            result = subprocess.run(
                ['sc', 'query', service_name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False # Do not raise exception on non-zero exit codes
            )
            
            if "FAILED 1060" in result.stderr:
                return ServiceStatus.UNKNOWN

            output = result.stdout.upper()
            if "RUNNING" in output:
                return ServiceStatus.RUNNING
            elif "STOPPED" in output:
                return ServiceStatus.STOPPED
            elif "START_PENDING" in output:
                return ServiceStatus.STARTING
            elif "STOP_PENDING" in output:
                return ServiceStatus.STOPPING
            
            return ServiceStatus.UNKNOWN
            
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout checking service status for {service_name}")
            return ServiceStatus.UNKNOWN
        except Exception as e:
            logger.error(f"Failed to check service status for {service_name}: {e}")
            return ServiceStatus.UNKNOWN
    
    def start_service(self, service_name: str) -> bool:
        try:
            logger.info(f"Starting service {service_name}...")
            result = subprocess.run(
                ['sc', 'start', service_name],
                capture_output=True,
                text=True,
                timeout=self.config.settings.service_restart_timeout
            )
            
            if result.returncode == 0 or "START_PENDING" in result.stdout:
                logger.info(f"Service {service_name} started successfully")
                return True
            else:
                logger.error(f"Failed to start service {service_name}: {result.stderr or result.stdout}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout starting service {service_name}")
            return False
        except Exception as e:
            logger.error(f"Error starting service {service_name}: {e}")
            return False

    def stop_service(self, service_name: str) -> bool:
        try:
            logger.info(f"Stopping service {service_name}...")
            result = subprocess.run(
                ['sc', 'stop', service_name],
                capture_output=True,
                text=True,
                timeout=self.config.settings.service_restart_timeout
            )
            
            if result.returncode == 0 or "The service is not started" in result.stderr:
                logger.info(f"Service {service_name} stopped successfully or was already stopped.")
                return True
            else:
                logger.error(f"Failed to stop service {service_name}: {result.stderr or result.stdout}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout stopping service {service_name}")
            return False
        except Exception as e:
            logger.error(f"Error stopping service {service_name}: {e}")
            return False

    def restart_service(self, service_name: str) -> bool:
        logger.info(f"Restarting service {service_name}")
        
        status = self.get_service_status(service_name)
        if status in [ServiceStatus.RUNNING, ServiceStatus.STARTING]:
            if not self.stop_service(service_name):
                return False
            
            max_wait = 30
            for _ in range(max_wait):
                if self.get_service_status(service_name) == ServiceStatus.STOPPED:
                    break
                time.sleep(1)
            else:
                logger.warning(f"Service {service_name} did not stop within {max_wait} seconds")
        
        return self.start_service(service_name)
    
    # ===================================================================
    # == NEW, COMBINED HEALTH CHECK LOGIC STARTS HERE
    # ===================================================================

    def handle_service(self, service_config: ServiceConfig) -> bool:
        """
        Handle a single service check with two-step logic:
        1. Check if the service is running.
        2. If running, perform a deep log check.
        """
        logger.info(f"Checking service: {service_config.name}")
        
        status = self.get_service_status(service_config.name)
        
        if status == ServiceStatus.STOPPED:
            logger.warning(f"Service {service_config.name} is stopped. Attempting to restart...")
            return self.restart_service(service_config.name)
            
        elif status == ServiceStatus.UNKNOWN:
            logger.error(f"Service {service_config.name} not found or inaccessible")
            return False

        elif status == ServiceStatus.RUNNING:
            logger.info(f"Service {service_config.name} is running. Proceeding to log check...")
            
            # Now that we know it's running, check the log file for deeper issues
            if service_config.log_enabled and service_config.checks:
                check_result, message = self.check_log_file(service_config)
                logger.info(f"Log check result for {service_config.name}: {check_result.value} - {message}")
                
                if check_result == CheckResult.FAILED:
                    logger.warning(f"Log check failed for running service {service_config.name}, restarting...")
                    return self.restart_service(service_config.name)
                elif check_result == CheckResult.ERROR:
                    logger.error(f"Log check error for {service_config.name}: {message}")
                    return False 
            
            # If service is running and log checks pass (or are disabled)
            logger.info(f"Service {service_config.name} is healthy.")
            return True
            
        else: # Covers STARTING, STOPPING states
            logger.info(f"Service {service_config.name} is in a transient state ({status.value}). No action taken this cycle.")
            return True

    def check_log_file(self, service_config: ServiceConfig) -> Tuple[CheckResult, str]:
        """
        Performs a specific, high-performance health check for SIL files.
        It verifies that 'CreateNewPTZIntance' appears after the last 'Log started'.
        """
        if not service_config.log_enabled or not service_config.checks:
            return CheckResult.PASSED, "No log checks configured"

        if not os.path.exists(service_config.log_path):
            return CheckResult.ERROR, f"Log file not found: {service_config.log_path}"

        try:
            logger.info(f"Performing specialized health check on {service_config.log_path}")
            with open(service_config.log_path, "rb") as f:
                data = f.read()

            strings = re.findall(rb"[ -~]{4,}", data)
            texts = [s.decode(self.config.settings.log_encoding, errors="ignore") for s in strings]

            if not texts:
                return CheckResult.ERROR, "Log file is empty or contains no readable strings"

            log_started_check_string = "Log started"
            last_log_started_index = -1
            for i, text in enumerate(texts):
                if log_started_check_string in text:
                    last_log_started_index = i
            
            if last_log_started_index == -1:
                return CheckResult.FAILED, "Critical: 'Log started' not found anywhere in the log file."

            ptz_instance_check_string = "CreateNewPTZIntance"
            last_ptz_instance_index = -1
            for i, text in enumerate(texts):
                if ptz_instance_check_string in text:
                    last_ptz_instance_index = i

            logger.info(f"Last 'Log started' found at index {last_log_started_index}. Last 'CreateNewPTZIntance' found at index {last_ptz_instance_index}.")
            if last_ptz_instance_index > last_log_started_index:
                return CheckResult.PASSED, "Health check passed: PTZ instance was created after the last log start."
            else:
                return CheckResult.FAILED, "Health check failed: PTZ instance was NOT created after the last log start."

        except Exception as e:
            return CheckResult.ERROR, f"Error during specialized log check: {e}"
    
    def update_database_settings(self, service_config: ServiceConfig) -> bool:
        """Update database settings for a service"""
        if not service_config.database_updates:
            return True
        
        try:
            db = next(get_db())
            success_count = 0
            
            for update in service_config.database_updates:
                try:
                    # Format the value template
                    formatted_value = update.set_value_template.format(
                        machine_ip=self.machine_ip,
                        machine_name=self.machine_name,
                        active_node=self.current_active_node
                    )
                    
                    # Execute update query
                    query = text(f"""
                    UPDATE {self.config.database.schema}.{update.table}
                    SET {update.set_column} = :value
                    WHERE {update.where_condition}
                    """)
                    
                    result = db.execute(query, {'value': formatted_value})
                    affected_rows = result.rowcount
                    db.commit()
                    
                    if affected_rows > 0:
                        logger.info(f"Updated {update.table}.{update.set_column} = '{formatted_value}' ({affected_rows} rows)")
                        success_count += 1
                    else:
                        logger.warning(f"No rows updated for {update.table} - condition may not match")
                        
                except Exception as e:
                    logger.error(f"Database update failed for {update.table}: {e}")
                    db.rollback()
            
            db.close()
            return success_count == len(service_config.database_updates)
            
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            return False
    
    def check_all_services(self) -> Dict[str, bool]:
        """Check all configured services"""
        results = {}
        
        for service_config in self.config.services:
            try:
                results[service_config.name] = self.handle_service(service_config)
            except Exception as e:
                logger.error(f"Error handling service {service_config.name}: {e}")
                results[service_config.name] = False
        
        return results
    
    def is_cluster_healthy(self) -> bool:
        """Check if the cluster is healthy (ViewScape service is running)"""
        if self.current_active_node is None:
            return self.discover_active_node() is not None
        
        # Check if current active node is still active
        if self.check_viewscape_service(self.current_active_node):
            return True
        
        # Try to discover new active node
        logger.warning("Current active node is no longer available, discovering new node...")
        return self.discover_active_node() is not None