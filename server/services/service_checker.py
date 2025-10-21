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
from config.config_loader import Config, ServiceConfig
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
        self.ptz_consecutive_failures = 0 # Tracks repeated failures for the new logic

    def _get_machine_name(self) -> str:
        """Get the current machine name"""
        import platform
        return platform.node()
    
    def _get_machine_ip(self) -> str:
        """Get the current machine IP"""
        for node in self.config.cluster.nodes:
            if os.path.normcase(node.name) == os.path.normcase(self.machine_name):
                return node.ip
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

    def get_cluster_owner_node(self) -> Optional[str]:
        """
        Get the current owner of the core cluster group from Windows Failover Cluster.
        Returns the node name or None if the command fails.
        """
        try:
            role_name = self.config.cluster.role_name
            command = f"powershell.exe -Command \"((Get-ClusterGroup '{role_name}').OwnerNode).Name\""
            logger.debug(f"Executing PowerShell command: {command}")
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=15, # Increased timeout
                check=False,
                shell=True
            )
            
            stdout_clean = result.stdout.strip() if result.stdout else "[No stdout]"
            stderr_clean = result.stderr.strip() if result.stderr else "[No stderr]"

            logger.debug(f"PowerShell command finished. Return Code: {result.returncode}, STDOUT: '{stdout_clean}', STDERR: '{stderr_clean}'")
            
            if result.returncode == 0 and result.stdout and result.stdout.strip():
                owner_node = result.stdout.strip()
                logger.info(f"Successfully determined Windows Cluster owner: {owner_node}")
                return owner_node
            else:
                logger.warning(f"Could not determine Windows Cluster owner. PS Error: {stderr_clean}")
                return None

        except subprocess.TimeoutExpired:
            logger.error("PowerShell command to get cluster owner timed out. This could indicate a cluster issue.")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred while checking cluster owner: {e}")
            return None
    
    def get_service_status(self, service_name: str) -> ServiceStatus:
        """Get the status of a Windows service"""
        try:
            result = subprocess.run(
                ['sc', 'query', service_name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False
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
        """Stops a service only if it is currently running."""
        current_status = self.get_service_status(service_name)
        if current_status == ServiceStatus.STOPPED:
            logger.debug(f"Service {service_name} is already stopped. No action needed.")
            return True
            
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

    def stop_all_services(self):
        """Helper function to stop all monitored services including ViewscapeMasterControl."""
        logger.info("Stopping all services on this node to switch to passive mode.")
        for service_config in self.config.services:
            self.stop_service(service_config.name)
        self.stop_service(self.config.viewscape.service_name)
        
    def restart_service(self, service_name: str) -> bool:
            """
            TESTING VERSION: Forcefully restarts a Windows service by directly killing the process.
            """
            logger.warning(f"TESTING: Attempting to FORCE-RESTART service: {service_name}")

            # 1. Find the PID and kill the process directly
            try:
                pid_query = subprocess.run(
                    ['sc', 'queryex', service_name],
                    capture_output=True, text=True, check=True
                )
                pid_match = re.search(r"PID\s+:\s+(\d+)", pid_query.stdout)
                if pid_match:
                    pid = pid_match.group(1)
                    if int(pid) > 0:
                        logger.info(f"Found service PID: {pid}. Forcefully terminating...")
                        kill_result = subprocess.run(
                            ['taskkill', '/F', '/PID', pid],
                            capture_output=True, text=True
                        )
                        logger.info(f"Taskkill output: {kill_result.stdout.strip() or kill_result.stderr.strip()}")
                        time.sleep(3) # Give OS a moment to clean up after the kill
                    else:
                        logger.info("Service reported PID of 0, it is not running. Proceeding to start.")
                else:
                    logger.warning("Could not find PID for the service. It might already be stopped. Proceeding to start.")
            except Exception as e:
                logger.error(f"Failed to find or kill process for {service_name}: {e}")

            # 2. Start the service
            return self.start_service(service_name)
    
    def handle_service(self, service_config: ServiceConfig) -> CheckResult:
        """
        Handle a single service check, now returning a CheckResult enum.
        """
        logger.info(f"Checking service: {service_config.name}")
        
        status = self.get_service_status(service_config.name)
        
        if status == ServiceStatus.STOPPED:
            logger.warning(f"Service {service_config.name} is stopped. Attempting to restart...")
            # --- MODIFICATION FOR TESTING ---
            # self.restart_service(service_config.name)
            logger.info(f"TESTING: Pretending to restart {service_config.name} but skipping it.")
            # Still return FAILED to trigger the escalation logic in main.py
            return CheckResult.FAILED
            
        elif status == ServiceStatus.UNKNOWN:
            logger.error(f"Service {service_config.name} not found or inaccessible")
            return CheckResult.ERROR

        elif status == ServiceStatus.RUNNING:
            logger.info(f"Service {service_config.name} is running. Proceeding to log check...")
            
            if service_config.log_enabled and service_config.checks:
                check_result, message = self.check_log_file(service_config)
                logger.info(f"Log check result for {service_config.name}: {check_result.value} - {message}")
                
                if check_result == CheckResult.FAILED:
                    logger.warning(f"Log check failed for running service {service_config.name}, restarting...")
                    self.restart_service(service_config.name)
                    return CheckResult.FAILED # Return failure to trigger new logic
                elif check_result == CheckResult.ERROR:
                    logger.error(f"Log check error for {service_config.name}: {message}")
                    return CheckResult.ERROR
            
            logger.info(f"Service {service_config.name} is healthy.")
            return CheckResult.PASSED
            
        else:
            logger.info(f"Service {service_config.name} is in a transient state ({status.value}). No action taken.")
            return CheckResult.PASSED
        
    def _find_latest_log_file(self, directory: str, pattern: str) -> Optional[str]:
        """
        Finds the latest log file in a directory based on a regex pattern
        that captures a timestamp.
        """
        if not os.path.isdir(directory):
            logger.error(f"Log directory not found: {directory}")
            return None

        latest_file = None
        latest_timestamp = None
        
        try:
            log_pattern = re.compile(pattern)
            for filename in os.listdir(directory):
                match = log_pattern.match(filename)
                if match:
                    # Assumes the first captured group is the timestamp
                    timestamp_str = match.group(1)
                    try:
                        file_timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d-%H-%M-%S")
                        if latest_timestamp is None or file_timestamp > latest_timestamp:
                            latest_timestamp = file_timestamp
                            latest_file = os.path.join(directory, filename)
                    except ValueError:
                        logger.warning(f"Could not parse timestamp from filename: {filename}")
            
            if latest_file:
                logger.debug(f"Found latest log file: {latest_file}")
            else:
                logger.warning(f"No log files matching pattern '{pattern}' found in '{directory}'.")

            return latest_file
        except Exception as e:
            logger.error(f"Error while searching for log files in '{directory}': {e}")
            return None


    def check_log_file(self, service_config: ServiceConfig) -> Tuple[CheckResult, str]:
        """
        Performs a health check by finding the latest log file and analyzing it.
        """
        if not service_config.log_enabled or not service_config.checks:
            return CheckResult.PASSED, "No log checks configured"

        # Dynamically find the latest log file
        log_path = self._find_latest_log_file(service_config.log_directory, service_config.log_file_pattern)

        if not log_path:
            return CheckResult.ERROR, f"No matching log files found in {service_config.log_directory}"
            
        if not os.path.exists(log_path):
            return CheckResult.ERROR, f"Latest log file not found: {log_path}"

        try:
            logger.debug(f"Performing health check on latest log: {log_path}")
            with open(log_path, "rb") as f:
                data = f.read()

            strings = re.findall(rb"[ -~]{4,}", data)
            texts = [s.decode(self.config.settings.log_encoding, errors="ignore") for s in strings]

            if not texts:
                return CheckResult.ERROR, "Log file is empty or contains no readable strings"

            log_started_check_string = "Log started"
            last_log_started_index = -1
            for i in range(len(texts) - 1, -1, -1):
                if log_started_check_string.lower() in texts[i].lower():
                    last_log_started_index = i
                    break
            
            if last_log_started_index == -1:
                return CheckResult.FAILED, "'Log started' not found in the log file."

            ptz_instance_check_string = "CreateNewPTZIntance"
            found_ptz_after_log_start = False
            for i in range(last_log_started_index, len(texts)):
                if ptz_instance_check_string.lower() in texts[i].lower():
                    found_ptz_after_log_start = True
                    break

            if found_ptz_after_log_start:
                return CheckResult.PASSED, "Health check passed: PTZ instance was created after the last log start."
            else:
                return CheckResult.FAILED, "Health check failed: PTZ instance was NOT created after the last log start."

        except Exception as e:
            return CheckResult.ERROR, f"Error during specialized log check: {e}"
    
    def check_initial_db_ip(self) -> None:
        """
        Queries and logs the current IP address stored in the database for a key service.
        """
        service_to_check = next((s for s in self.config.services if s.database_updates), None)

        if not service_to_check:
            logger.info("No services configured for database updates. Skipping initial IP check.")
            return

        db_update_config = service_to_check.database_updates[0]
        
        try:
            with engine.connect() as connection:
                query = text(f"SELECT {db_update_config.set_column} FROM {self.config.database.schema}.{db_update_config.table} WHERE {db_update_config.where_condition}")
                result = connection.execute(query).fetchone()
                
                if result:
                    current_ip = result[0]
                    logger.info(f"Initial database check: Found IP '{current_ip}' for target '{db_update_config.where_condition}'.")
                else:
                    logger.warning(f"Initial database check: Could not find a record for where condition: {db_update_config.where_condition}")

        except Exception as e:
            logger.error(f"Initial database check failed: {e}")

    def update_database_for_all_services(self) -> None:
        """
        Iterates through all monitored services and updates the database settings.
        This is intended to be called on a cluster failover event.
        """
        logger.info("Updating database settings for all monitored services following owner change.")
        for service_config in self.config.services:
            if service_config.database_updates:
                self.update_database_settings(service_config)
    
    def update_database_settings(self, service_config: ServiceConfig) -> bool:
        """Update database settings for a service"""
        if not service_config.database_updates:
            return True
        
        try:
            with engine.connect() as connection:
                trans = connection.begin()
                success_count = 0
                for update in service_config.database_updates:
                    try:
                        formatted_value = update.set_value_template.format(machine_ip=self.machine_ip)
                        query = text(f"UPDATE {self.config.database.schema}.{update.table} SET {update.set_column} = :value WHERE {update.where_condition}")
                        result = connection.execute(query, {'value': formatted_value})
                        logger.info(f"Updated {result.rowcount} rows in {update.table} with value '{formatted_value}'")
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Database update failed for {update.table}: {e}")
                trans.commit()
                return success_count > 0
        except Exception as e:
            logger.error(f"Database connection failed during update: {e}")
            return False

    def check_all_services(self) -> Dict[str, bool]:
        """Check all configured services"""
        results = {}
        for service_config in self.config.services:
            results[service_config.name] = self.handle_service(service_config)
        return results