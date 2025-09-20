import pyodbc
import time
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import traceback

# =========================
# Configuration
# =========================
CONFIG = {
    "server": "172.16.10.80",
    "database": "vtasdata_test1",
    "username": "sa",         # Leave empty for Windows Auth
    "password": "m00se_1234",  # Leave empty for Windows Auth
    "target_machines": ["VERACITY-APPV1", "VERACITY-APPV2"],
    "machine_ips": {
        "VERACITY-APPV1": "172.16.10.56:51052",
        "VERACITY-APPV2": "172.16.10.57:51052"
    },
    "connection_timeout": 30,
    "check_interval_seconds": 10,
    "max_retries": 3,
    "retry_delay_seconds": 5,
    "log_path": r"E:\PTZ_logs\vtasdata_test1_Monitor.log",
    "log_max_size_mb": 100
}

# =========================
# Logging Setup
# =========================
os.makedirs(os.path.dirname(CONFIG["log_path"]), exist_ok=True)
logger = logging.getLogger("DBMonitor")
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    CONFIG["log_path"],
    maxBytes=CONFIG["log_max_size_mb"] * 1024 * 1024,
    backupCount=5
)
file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Log any uncaught exceptions
def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_uncaught_exception

# =========================
# SQL Connection Helper
# =========================
def get_connection():
    if CONFIG["username"] and CONFIG["password"]:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={CONFIG['server']};"
            f"DATABASE={CONFIG['database']};"
            f"UID={CONFIG['username']};PWD={CONFIG['password']};"
            f"Connection Timeout={CONFIG['connection_timeout']}"
        )
    else:
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={CONFIG['server']};"
            f"DATABASE={CONFIG['database']};"
            "Trusted_Connection=yes;"
            f"Connection Timeout={CONFIG['connection_timeout']}"
        )
    return pyodbc.connect(conn_str)

def execute_query(query, retries=0):
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                if cursor.description:
                    return cursor.fetchall()
                else:
                    conn.commit()
                    return None
    except Exception as e:
        logger.error(f"Error executing query (Attempt {retries + 1}): {e}")
        if retries < CONFIG["max_retries"]:
            time.sleep(CONFIG["retry_delay_seconds"])
            return execute_query(query, retries + 1)
        return None

# =========================
# Main Monitoring Logic - One iteration only
# =========================
def monitor_loop():
    try:
        target_list_sql = ", ".join(f"'{m}'" for m in CONFIG["target_machines"])
        connection_query = f"""
        SELECT DISTINCT 
            s.host_name,
            s.session_id,
            s.login_time,
            s.login_name
        FROM sys.dm_exec_sessions s
        WHERE s.database_id = DB_ID('{CONFIG['database']}')
            AND s.host_name IN ({target_list_sql})
            AND s.is_user_process = 1
            AND s.status = 'running'
        ORDER BY s.host_name, s.login_time DESC
        """

        connections = execute_query(connection_query)

        if connections:
            processed = set()
            for row in connections:
                machine_name = row[0]
                if machine_name in processed:
                    continue
                processed.add(machine_name)

                logger.info(f"Active connection from {machine_name} (Session {row[1]}, User {row[3]})")

                update_query = f"""
                UPDATE MySettings_TBL
                SET mysValue_TXT = '{CONFIG["machine_ips"][machine_name]}'
                WHERE mysName_TXT LIKE '%MilestonePTZServerTarget%'
                """
                execute_query(update_query)
                logger.info(f"Updated MilestonePTZServerTarget for {machine_name}")

                if machine_name == "VERACITY-APPV1":
                    version_query = "SELECT TOP 1 verVersionReference_TXT FROM Version_TBL"
                    version_result = execute_query(version_query)
                    if version_result:
                        logger.info(f"Version Reference: {version_result[0][0]}")
                    else:
                        logger.warning("No version reference found in Version_TBL")
        else:
            logger.info("No active connections found from target machines.")

    except Exception as e:
        logger.error(f"Error in main monitoring loop: {e}")
        logger.error(traceback.format_exc())

# =========================
# Entry Point - Run only 5 times
# =========================
def main():
    logger.info("=== Starting vtasdata_test1 Connection Monitor ===")
    for cycle in range(5):  # Run only 5 times
        logger.info(f"--- Cycle {cycle+1} of 5 ---")
        try:
            test_result = execute_query("SELECT 1 AS TestConnection")
            if test_result:
                logger.info("Database connection successful!")
                monitor_loop()
            else:
                logger.error("Failed to connect to database. Retrying...")
        except Exception as e:
            logger.error(f"Startup error: {e}")
            logger.error(traceback.format_exc())
        time.sleep(CONFIG["check_interval_seconds"])
    logger.info("=== Monitoring completed after 5 cycles. Exiting. ===")

if __name__ == "__main__":
    main()
