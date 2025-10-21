import yaml
import os
import sys
import json
import subprocess
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import logging

# NEW: Import decryption utility
try:
    from .decrypt import decrypt_data
except ImportError:
    from decrypt import decrypt_data # Fallback for direct script run

# Logger is defined, but load_config will use print() before it's configured
logger = logging.getLogger(__name__)


CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
# Encrypted file paths
ENCRYPTED_CONFIG_PATH = os.path.join(CONFIG_DIR, 'encrypted_config.dat')
PRIVATE_KEY_PATH = os.path.join(CONFIG_DIR, 'private_key.pem')

# Path to the GUI tool
GUI_TOOL_PATH = os.path.normpath(os.path.join(CONFIG_DIR, '..', '..', 'GUI', 'main_gui.py'))
PYTHON_EXECUTABLE = sys.executable 

@dataclass
class EnvConfig:
    DB_SERVER: str
    DB_DATABASE: str
    DB_USERNAME: str
    DB_PASSWORD: str

@dataclass
class NodeConfig:
    name: str
    ip: str
    port: int

@dataclass
class ClusterConfig:
    name: str
    role_name: str
    nodes: List[NodeConfig]

@dataclass
class ViewScapeConfig:
    service_name: str
    ports: List[int]
    connection_timeout: int

@dataclass
class LogCheck:
    find_string: str
    action: str
    search_lines: Optional[int] = None

@dataclass
class DatabaseUpdate:
    table: str
    set_column: str
    set_value_template: str
    where_condition: str

@dataclass
class ServiceConfig:
    name: str
    log_enabled: bool
    sil_file: bool
    checks: List[LogCheck]
    database_updates: List[DatabaseUpdate]
    log_directory: Optional[str] = None
    log_file_pattern: Optional[str] = None
    
@dataclass
class ServiceGUIConfig:
    name: str
    instruction: str

@dataclass
class SettingsConfig:
    check_interval: int
    service_restart_timeout: int
    log_encoding: str
    max_log_lines_to_check: int
    communication_port: Optional[int] = 12345

@dataclass
class LoggingConfig:
    level: str
    file_path: str
    max_file_size: int
    backup_count: int
    format: str

@dataclass
class DatabaseConfig:
    schema: str
    connection_pool: Dict[str, Any]

@dataclass
class Config:
    env: EnvConfig
    cluster: ClusterConfig
    viewscape: ViewScapeConfig
    services: List[ServiceConfig]
    services_GUI: List[ServiceGUIConfig]
    settings: SettingsConfig
    logging: LoggingConfig
    database: DatabaseConfig

def _launch_setup_gui():
    """Launches the PyQt setup tool and waits for it to complete."""
    print("\n" + "="*60)
    print("      *** SENSITIVE CONFIGURATION NOT FOUND ***")
    print("="*60)
    print("Launching the configuration setup tool...")
    print("Please fill in all details in the GUI and click 'Generate'.")
    print("The server will wait for the GUI to close before retrying.")
    print("="*60 + "\n")
    
    try:
        subprocess.run([PYTHON_EXECUTABLE, GUI_TOOL_PATH], check=True)
        print("Setup tool closed. Retrying configuration load...")
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Setup tool process failed or was cancelled. {e}")
        return False
    except FileNotFoundError:
        print(f"CRITICAL ERROR: Could not find setup tool at {GUI_TOOL_PATH}")
        return False
    except Exception as e:
        print(f"CRITICAL ERROR: An unknown error occurred launching GUI: {e}")
        return False


class ConfigLoader:
    """Configuration loader for the service controller"""
    
    def __init__(self, config_path: str = "config.yaml"):
        # This path is now the *BASE* (non-sensitive) config
        self.base_config_path = os.path.join(CONFIG_DIR, config_path)
        self._config: Optional[Config] = None
    
    def load_config(self) -> Config:
        """
        Loads base config.yaml and merges encrypted config over it.
        """
        # 1. Load base (non-sensitive) config.yaml
        try:
            if not os.path.exists(self.base_config_path):
                raise FileNotFoundError(f"Base configuration file not found: {self.base_config_path}")
            with open(self.base_config_path, 'r', encoding='utf-8') as file:
                base_config_data = yaml.safe_load(file)
            print(f"Base configuration loaded from {self.base_config_path}")
        except Exception as e:
            print(f"CRITICAL ERROR: Failed to load base configuration: {e}")
            sys.exit(1)

        # 2. Loop to load and merge sensitive (encrypted) config
        loaded_encrypted = False
        decrypted_config = {}
        while not loaded_encrypted:
            try:
                with open(ENCRYPTED_CONFIG_PATH, 'r') as f:
                    encrypted_b64_string = f.read()
                decrypted_config = decrypt_data(encrypted_b64_string, PRIVATE_KEY_PATH)
                print("Encrypted config decrypted successfully.")
                loaded_encrypted = True
            except FileNotFoundError as e:
                print(f"\nFile not found: {e.filename}")
                if not _launch_setup_gui():
                    print("Server cannot start without configuration. Exiting.")
                    sys.exit(1)
            except Exception as e:
                print(f"CRITICAL ERROR: Failed to decrypt configuration: {e}")
                sys.exit(1)

        #    We NO LONGER set os.environ.
        #    We just merge the dictionaries.
        merged_config_data = base_config_data
        
        if 'env' in decrypted_config:
            merged_config_data['env'] = decrypted_config['env']
        if 'cluster' in decrypted_config:
            merged_config_data['cluster'] = decrypted_config['cluster']
        if 'services' in decrypted_config:
            merged_config_data['services'] = decrypted_config['services']
        if 'services_GUI' in decrypted_config:
            merged_config_data['services_GUI'] = decrypted_config['services_GUI']

        # 4. Parse the *final* merged data into dataclasses
        try:
            self._config = self._parse_config(merged_config_data)
            print("Configuration merged and parsed successfully.")
            return self._config
        except Exception as e:
            print(f"CRITICAL ERROR: Failed to parse final merged configuration: {e}")
            print("Check base config.yaml and GUI YAML inputs for schema errors.")
            sys.exit(1)

    
    def _parse_config(self, config_data: Dict[str, Any]) -> Config:
        """Parse configuration data into structured objects"""
        
        env_data = config_data.get('env')
        if not env_data:
            raise ValueError("Encrypted 'env' data with DB credentials is missing from config.")
        env = EnvConfig(**env_data)
        
        cluster_data = config_data['cluster']
        nodes = [
            NodeConfig(name=node['name'], ip=node['ip'], port=node['port'])
            for node in cluster_data['nodes']
        ]
        cluster = ClusterConfig(
            name=cluster_data['name'],
            role_name=cluster_data['role_name'],
            nodes=nodes
        )
        
        viewscape_data = config_data['viewscape']
        viewscape = ViewScapeConfig(
            service_name=viewscape_data['service_name'],
            ports=viewscape_data['ports'],
            connection_timeout=viewscape_data['connection_timeout']
        )
        
        services_gui_data = [ServiceGUIConfig(**s) for s in config_data.get('services_GUI', [])]
        
        services = []
        for service_data in config_data['services']:
            checks = [
                LogCheck(
                    find_string=check['find_string'],
                    action=check['action'],
                    search_lines=check.get('search_lines')
                )
                for check in service_data.get('checks', [])
            ]
            
            db_updates = [
                DatabaseUpdate(
                    table=update['table'],
                    set_column=update['set_column'],
                    set_value_template=update['set_value_template'],
                    where_condition=update['where_condition']
                )
                for update in service_data.get('database_updates', [])
            ]
            
            service = ServiceConfig(
                name=service_data['name'],
                log_enabled=service_data['log_enabled'],
                log_directory=service_data.get('log_directory'),
                log_file_pattern=service_data.get('log_file_pattern'),
                sil_file=service_data['sil_file'],
                checks=checks,
                database_updates=db_updates
            )
            services.append(service)
        
        settings = SettingsConfig(**config_data['settings'])
        logging_config = LoggingConfig(**config_data['logging'])
        database = DatabaseConfig(**config_data['database'])
        
        # --- 5. RETURN FINAL OBJECT (MODIFIED) ---
        return Config(
            env=env,  # <-- Pass the new env object
            cluster=cluster,
            viewscape=viewscape,
            services=services,
            services_GUI=services_gui_data,
            settings=settings,
            logging=logging_config,
            database=database
        )
    
    def get_config(self) -> Config:
        """Get the loaded configuration"""
        if self._config is None:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        return self._config
    
    def get_service_config(self, service_name: str) -> Optional[ServiceConfig]:
        """Get configuration for a specific service"""
        if self._config is None:
            return None
        
        for service in self._config.services:
            if service.name == service_name:
                return service
        return None
    
    def get_node_by_name(self, node_name: str) -> Optional[NodeConfig]:
        """Get node configuration by name"""
        if self._config is None:
            return None
        
        for node in self._config.cluster.nodes:
            if node.name == node_name:
                return node
        return None
    
    def get_node_by_ip(self, ip: str) -> Optional[NodeConfig]:
        """Get node configuration by IP"""
        if self._config is None:
            return None
        
        for node in self._config.cluster.nodes:
            if node.ip == ip:
                return node
        return None
    
    def validate_config(self) -> bool:
        """Validate the loaded configuration"""
        if self._config is None:
            return False
        
        try:
            if not self._config.cluster.nodes:
                logger.error("No nodes defined in cluster configuration")
                return False
            
            for service in self._config.services:
                if service.log_enabled and not service.log_directory:
                    logger.error(f"Service '{service.name}' has log_enabled=true but no log_directory specified")
                    return False
                
                for check in service.checks:
                    if check.action not in ['find_last', 'find_after_previous', 'find_first']:
                        logger.error(f"Invalid log check action '{check.action}' in service '{service.name}'")
                        return False
            
            logger.info("Configuration validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            return False
    
    def reload_config(self) -> Config:
        """Reload configuration from file"""
        logger.info("Reloading configuration...")
        return self.load_config()
    
    def save_default_config(self, path: str = "config.yaml"):
        # This method is now less useful, as it doesn't save the encrypted parts.
        # It's fine to leave it, but it will only save a *base* template.
        logger.warning("Saving default config. This does NOT include sensitive data.")
        # (The rest of your save_default_config method is fine)
        default_config = {
            # ... (your default config) ...
        }
        with open(path, 'w', encoding='utf-8') as file:
            yaml.dump(default_config, file, default_flow_style=False, indent=2)
        logger.info(f"Default configuration saved to {path}")

# NOTE: The global functions at the end of your original file are removed,
# as your main.py creates its own ConfigLoader instance.