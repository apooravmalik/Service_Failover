import socket
import time
import subprocess
import os
import logging
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from datetime import datetime
from sqlalchemy import text
from config.config_loader import Config, ServiceConfig, LogCheck, get_config
from db.database import get_db, engine
from utils.utils import LogFileReader, read_log_file_lines

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
        node = self.config.cluster.nodes[0]  # Default
        for node in self.config.cluster.nodes:
            if node.name.upper() == self.machine_name.upper():
                return node.ip
        return node.ip  # Fallback to first node IP
    
    def check_tcp_connection(self, ip: str, port: int, timeout: int = None) -> bool:
        """Check if TCP connection is available on given IP and port"""
        if timeout is None:
            timeout = self.config.viewscape.connection_timeout
            
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"TCP connection check failed for {ip}:{port} - {e}")
            return False
    
    def check_viewscape_service(self, ip: str) -> bool:
        """Check if ViewScape Service is running on the specified ports"""
        logger.debug(f"Checking ViewScape service on {ip}")
        
        for port in self.config.viewscape.ports:
            if not self.check_tcp_connection(ip, port):
                logger.debug(f"ViewScape port {port} not available on {ip}")
                return False
        
        logger.info(f"ViewScape Service confirmed running on {ip}")
        return True
    
    def discover_active_node(self) -> Optional[str]:
        """Discover which node has ViewScape Service running"""
        logger.info("Discovering active ViewScape node...")
        
        # Check default primary node first
        primary_node = None
        for node in self.config.cluster.nodes:
            if node.name == self.config.cluster.default_primary_node:
                primary_node = node
                break
        
        if primary_node and self.check_viewscape_service(primary_node.ip):
            logger.info(f"Primary node {primary_node.name} ({primary_node.ip}) is active")
            self.current_active_node = primary_node.ip
            return primary_node.ip
        
        # Check other nodes
        for node in self.config.cluster.nodes:
            if node.name != self.config.cluster.default_primary_node:
                if self.check_viewscape_service(node.ip):
                    logger.info(f"Node {node.name} ({node.ip}) is active")
                    self.current_active_node = node.ip
                    return node.ip
        
        logger.error("No active ViewScape node found")
        self.current_active_node = None
        return None
    
    def get_service_status(self, service_name: str) -> ServiceStatus:
        """Get the status of a Windows service"""
        try:
            result = subprocess.run(
                ['sc', 'query', service_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
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
        """Start a Windows service"""
        try:
            logger.info(f"Starting service {service_name}...")
            result = subprocess.run(
                ['sc', 'start', service_name],
                capture_output=True,
                text=True,
                timeout=self.config.settings.service_restart_timeout
            )
            
            if result.returncode == 0:
                logger.info(f"Service {service_name} started successfully")
                return True
            else:
                logger.error(f"Failed to start service {service_name}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout starting service {service_name}")
            return False
        except Exception as e:
            logger.error(f"Error starting service {service_name}: {e}")
            return False
    
    def stop_service(self, service_name: str) -> bool:
        """Stop a Windows service"""
        try:
            logger.info(f"Stopping service {service_name}...")
            result = subprocess.run(
                ['sc', 'stop', service_name],
                capture_output=True,
                text=True,
                timeout=self.config.settings.service_restart_timeout
            )
            
            if result.returncode == 0:
                logger.info(f"Service {service_name} stopped successfully")
                return True
            else:
                logger.error(f"Failed to stop service {service_name}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout stopping service {service_name}")
            return False
        except Exception as e:
            logger.error(f"Error stopping service {service_name}: {e}")
            return False
    
    def restart_service(self, service_name: str) -> bool:
        """Restart a Windows service"""
        logger.info(f"Restarting service {service_name}")
        
        # Stop the service if it's running
        status = self.get_service_status(service_name)
        if status in [ServiceStatus.RUNNING, ServiceStatus.STARTING]:
            if not self.stop_service(service_name):
                return False
            
            # Wait for service to fully stop
            max_wait = 10
            for _ in range(max_wait):
                if self.get_service_status(service_name) == ServiceStatus.STOPPED:
                    break
                time.sleep(1)
            else:
                logger.warning(f"Service {service_name} did not stop within {max_wait} seconds")
        
        # Start the service
        return self.start_service(service_name)
    
    def check_log_file(self, service_config: ServiceConfig) -> Tuple[CheckResult, str]:
        """Check log file based on service configuration"""
        if not service_config.log_enabled or not service_config.checks:
            return CheckResult.PASSED, "No log checks configured"
        
        if not os.path.exists(service_config.log_path):
            return CheckResult.ERROR, f"Log file not found: {service_config.log_path}"
        
        try:
            # Use unified log reader that supports both text and SIL formats
            max_lines = self.config.settings.max_log_lines_to_check
            lines = read_log_file_lines(
                service_config.log_path,
                encoding=self.config.settings.log_encoding,
                max_lines=max_lines,
                is_sil=service_config.sil_file
            )

            if not lines:
                return CheckResult.ERROR, "Log file is empty or unreadable"
            
            return self._process_log_checks(lines, service_config.checks)

        except Exception as e:
            return CheckResult.ERROR, f"Error reading log file: {e}"
    
    def _process_log_checks(self, lines: List[str], checks: List[LogCheck]) -> Tuple[CheckResult, str]:
        """Process log checks according to configuration"""
        previous_index = -1
        
        for i, check in enumerate(checks):
            if check.action == "find_last":
                # Find last occurrence of string
                found_index = -1
                for j in range(len(lines) - 1, -1, -1):
                    if check.find_string in lines[j]:
                        found_index = j
                        break
                
                if found_index == -1:
                    return CheckResult.FAILED, f"String '{check.find_string}' not found"
                
                previous_index = found_index
                logger.debug(f"Found '{check.find_string}' at line {found_index + 1}")
                
            elif check.action == "find_first":
                # Find first occurrence of string
                found_index = -1
                for j, line in enumerate(lines):
                    if check.find_string in line:
                        found_index = j
                        break
                
                if found_index == -1:
                    return CheckResult.FAILED, f"String '{check.find_string}' not found"
                
                previous_index = found_index
                logger.debug(f"Found '{check.find_string}' at line {found_index + 1}")
                
            elif check.action == "find_after_previous":
                if previous_index == -1:
                    return CheckResult.ERROR, f"Cannot find '{check.find_string}' after previous - no previous index"
                
                search_lines = check.search_lines or 50
                end_index = min(previous_index + search_lines, len(lines))
                
                found = False
                for j in range(previous_index, end_index):
                    if check.find_string in lines[j]:
                        logger.debug(f"Found '{check.find_string}' at line {j + 1}")
                        previous_index = j
                        found = True
                        break
                
                if not found:
                    return CheckResult.FAILED, f"String '{check.find_string}' not found within {search_lines} lines after previous check"
            
            else:
                return CheckResult.ERROR, f"Unknown log check action: {check.action}"
        
        return CheckResult.PASSED, "All log checks passed"
    
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
    
    def handle_service(self, service_config: ServiceConfig) -> bool:
        """Handle a single service check and restart if needed"""
        logger.info(f"Checking service: {service_config.name}")
        
        # Check if service exists
        status = self.get_service_status(service_config.name)
        if status == ServiceStatus.UNKNOWN:
            logger.error(f"Service {service_config.name} not found or inaccessible")
            return False
        
        # Check log file if enabled
        if service_config.log_enabled and service_config.checks:
            check_result, message = self.check_log_file(service_config)
            logger.info(f"Log check result for {service_config.name}: {check_result.value} - {message}")
            
            if check_result == CheckResult.FAILED:
                logger.info(f"Log check failed for {service_config.name}, restarting service...")
                
                # Update database settings before restart
                if service_config.database_updates:
                    if not self.update_database_settings(service_config):
                        logger.error(f"Database update failed for {service_config.name}")
                        return False
                
                # Restart the service
                if self.restart_service(service_config.name):
                    logger.info(f"Service {service_config.name} restarted successfully")
                    return True
                else:
                    logger.error(f"Failed to restart service {service_config.name}")
                    return False
                    
            elif check_result == CheckResult.ERROR:
                logger.error(f"Log check error for {service_config.name}: {message}")
                return False
        
        # Service is running normally
        logger.info(f"Service {service_config.name} is running normally")
        return True
    
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