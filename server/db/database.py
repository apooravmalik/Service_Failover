# server/db/database.py
import os
import pyodbc
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, scoped_session
import logging

# --- 1. IMPORT THE DATACLASS ---
from config.config_loader import EnvConfig
# -------------------------------

logger = logging.getLogger(__name__)

# Globals, initialized as None
engine = None
SessionLocal = None

def init_db_engine(env_config: EnvConfig):
    """
    Initializes the database engine and session using
    credentials passed from the config object.
    """
    global engine, SessionLocal
    
    print(env_config)
    
    # 3. Read credentials *directly from the config object*
    #    (We only check os.environ for the non-sensitive driver)
    driver = os.environ.get("DB_DRIVER", "{ODBC Driver 17 for SQL Server}")
    server = env_config.DB_SERVER
    database = env_config.DB_DATABASE
    username = env_config.DB_USERNAME
    password = env_config.DB_PASSWORD

    if not server or not database or not username or not password:
         logger.error("Database credentials missing from config object. Cannot initialize engine.")
         return False

    # 4. Create connection string and engine
    try:
        connection_string = f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}"
        connection_url = URL.create("mssql+pyodbc", query={"odbc_connect": connection_string})

        engine = create_engine(connection_url, pool_recycle=3600, pool_pre_ping=True)
        SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
        
        logger.info("Database engine initialized successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        return False

def get_db():
    """
    Returns a new database session.
    """
    if SessionLocal is None:
        logger.error("Database not initialized. Call init_db_engine() first.")
        raise RuntimeError("Database not initialized.")
        
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

def test_connection() -> bool:
    """
    Tests the connection using the initialized engine.
    """
    if engine is None:
        logger.error("Database engine not initialized. Cannot test connection.")
        return False
        
    try:
        with engine.connect() as connection:
            logger.info("Successfully connected to the database!")
            return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False