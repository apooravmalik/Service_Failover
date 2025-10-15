import yaml
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class NodeConfig:
    name: str
    ip: str

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
    cluster: ClusterConfig
    viewscape: ViewScapeConfig
    services: List[ServiceConfig]
    settings: SettingsConfig
    logging: LoggingConfig
    database: DatabaseConfig

class ConfigLoader:
    """Configuration loader for the service controller"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._config: Optional[Config] = None
    
    def load_config(self) -> Config:
        """Load configuration from YAML file"""
        try:
            if not os.path.exists(self.config_path):
                raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
            
            with open(self.config_path, 'r', encoding='utf-8') as file:
                config_data = yaml.safe_load(file)
            
            self._config = self._parse_config(config_data)
            logger.info(f"Configuration loaded successfully from {self.config_path}")
            return self._config
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise
    
    def _parse_config(self, config_data: Dict[str, Any]) -> Config:
        """Parse configuration data into structured objects"""
        
        cluster_data = config_data['cluster']
        nodes = [
            NodeConfig(name=node['name'], ip=node['ip'])
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
        
        return Config(
            cluster=cluster,
            viewscape=viewscape,
            services=services,
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
        """Save a default configuration template"""
        default_config = {
            'cluster': {
                'name': 'VERACITY-CLUSTER',
                'role_name': 'VMC',
                'nodes': [
                    {'name': 'TVPS', 'ip': '10.***.*.173'},
                    {'name': 'TVPS2', 'ip': '10.***.*.205'}
                ]
            },
            'viewscape': {
                'service_name': 'ViewscapeMasterControl',
                'ports': [500, 12345],
                'connection_timeout': 5
            },
            'services': [
                {
                    'name': 'Veracity_PTZ',
                    'log_enabled': True,
                    'log_directory': 'C:\\Logs\\PTZ\\',
                    'log_file_pattern': 'proserver-(\\d{4}-\\d{2}-\\d{2}-\\d{2}-\\d{2}-\\d{2})\\.sil',
                    'sil_file': True,
                    'checks': [
                        {'find_string': 'Log started', 'action': 'find_last'},
                        {'find_string': 'CreatedNewPTZInstance', 'action': 'find_after_previous', 'search_lines': 25}
                    ],
                    'database_updates': [
                        {
                            'table': 'MySettings_TBL',
                            'set_column': 'mysValue_TXT',
                            'set_value_template': '{machine_ip}',
                            'where_condition': "mysName_TXT LIKE '%MilestonePTZServerTarget%'"
                        }
                    ]
                }
            ],
            'settings': {
                'check_interval': 30,
                'service_restart_timeout': 60,
                'log_encoding': 'utf-8',
                'max_log_lines_to_check': 1000,
                'communication_port': 12345
            },
            'logging': {
                'level': 'INFO',
                'file_path': 'service_controller.log',
                'max_file_size': 10485760,
                'backup_count': 5,
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            },
            'database': {
                'schema': 'dbo',
                'connection_pool': {
                    'size': 5,
                    'max_overflow': 10,
                    'timeout': 30,
                    'recycle': 3600
                }
            }
        }
        
        with open(path, 'w', encoding='utf-8') as file:
            yaml.dump(default_config, file, default_flow_style=False, indent=2)
        
        logger.info(f"Default configuration saved to {path}")


# Global config loader instance
config_loader = ConfigLoader()

def get_config() -> Config:
    """Get the global configuration instance"""
    return config_loader.get_config()

def load_config(config_path: str = "config.yaml") -> Config:
    """Load configuration from specified path"""
    global config_loader
    config_loader = ConfigLoader(config_path)
    return config_loader.load_config()