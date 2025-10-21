import sys
import os
import yaml
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QMessageBox, QTabWidget, QFormLayout
)
from crypto import encrypt_data

# --- Define all necessary paths ---
# Path to the directory this script is in (e.g., .../GUI/)
SETUP_DIR = os.path.dirname(os.path.abspath(__file__))
print(f"Setup Directory: {SETUP_DIR}")

# Path to the server's config directory (e.g., .../server/config/)
SERVER_CONFIG_DIR = os.path.join(SETUP_DIR, '..', 'server', 'config')

# Public key stays with the GUI (e.g., .../GUI/public_key.pem)
PUBLIC_KEY_PATH = os.path.join(SETUP_DIR, 'public_key.pem')

# Private key goes to the server (e.g., .../server/config/private_key.pem)
PRIVATE_KEY_PATH = os.path.join(SERVER_CONFIG_DIR, 'private_key.pem')

ENCRYPTED_CONFIG_PATH = os.path.join(SERVER_CONFIG_DIR, 'encrypted_config.dat')
GENERATOR_SCRIPT_PATH = os.path.join(SETUP_DIR, 'generate_keys.py')
# ------------------------------------

# --- Example YAML templates ---
CLUSTER_EXAMPLE = """
name: "VERACITY-CLUSTER"
role_name: "ViewScape-Master"
default_primary_node: "VERACITY-oldVPN"
nodes:
  - name: "VERACITY-oldVPN"
    ip: "10.0.0.1"
    port: 5000
  - name: "VERACITY-Kafka" 
    ip: "10.0.0.2"
    port: 5000
"""

SERVICES_TO_MONITOR_EXAMPLE = """
- name: "Veracity_PTZ"
  log_enabled: true
  log_directory: "C:/Path/To/Log/Dir"
  log_file_pattern: 'proserver-(\\d{4}-\\d{2}-\\d{2}-\\d{2}-\\d{2}-\\d{2})\\.sil'
  sil_file: true
  checks:
    - find_string: "Log started"
      action: "find_last"
  database_updates:
    - table: "MySettings_TBL"
      set_column: "mysValue_TXT"
      set_value_template: "{machine_ip}"
      where_condition: "mysName_TXT LIKE '%MilestonePTZServerTarget%'"
"""

SERVICES_GUI_EXAMPLE = """
- name: "Veracity_PTZ"
  instruction: "The PTZ service has stopped. Check logs."
- name: "ViewscapeMasterControl"
  instruction: "The master control service is critical. Attempt a manual restart."
"""


class ConfigApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Server Configuration Generator')
        self.setGeometry(300, 300, 700, 600)
        
        main_layout = QVBoxLayout()
        tabs = QTabWidget()

        # --- Tab 1: .env / Database ---
        env_tab = QWidget()
        env_layout = QFormLayout()
        self.db_server_input = QLineEdit("APOORAV_MALIK")
        self.db_name_input = QLineEdit("sop-manage")
        self.db_user_input = QLineEdit("sa")
        self.db_pass_input = QLineEdit("M00se1980")
        self.db_pass_input.setEchoMode(QLineEdit.Password)
        env_layout.addRow(QLabel('DB Server:'), self.db_server_input)
        env_layout.addRow(QLabel('DB Name:'), self.db_name_input)
        env_layout.addRow(QLabel('DB User:'), self.db_user_input)
        env_layout.addRow(QLabel('DB Password:'), self.db_pass_input)
        env_tab.setLayout(env_layout)

        # --- Tab 2: Cluster Config ---
        cluster_tab = QWidget()
        cluster_layout = QVBoxLayout()
        cluster_layout.addWidget(QLabel("Paste the YAML for 'cluster' configuration below:"))
        self.cluster_text_edit = QTextEdit()
        self.cluster_text_edit.setText(CLUSTER_EXAMPLE)
        self.cluster_text_edit.setAcceptRichText(False)
        cluster_layout.addWidget(self.cluster_text_edit)
        cluster_tab.setLayout(cluster_layout)

        # --- Tab 3: Services to Monitor ---
        monitor_tab = QWidget()
        monitor_layout = QVBoxLayout()
        monitor_layout.addWidget(QLabel("Paste the YAML for 'services' (Services to Monitor) below:"))
        self.monitor_text_edit = QTextEdit()
        self.monitor_text_edit.setText(SERVICES_TO_MONITOR_EXAMPLE)
        self.monitor_text_edit.setAcceptRichText(False)
        monitor_layout.addWidget(self.monitor_text_edit)
        monitor_tab.setLayout(monitor_layout)
        
        # --- Tab 4: GUI Services ---
        gui_tab = QWidget()
        gui_layout = QVBoxLayout()
        gui_layout.addWidget(QLabel("Paste the YAML for 'services_GUI' below:"))
        self.gui_text_edit = QTextEdit()
        self.gui_text_edit.setText(SERVICES_GUI_EXAMPLE)
        self.gui_text_edit.setAcceptRichText(False)
        gui_layout.addWidget(self.gui_text_edit)
        gui_tab.setLayout(gui_layout)

        # --- Add tabs to widget ---
        tabs.addTab(env_tab, ".env Details")
        tabs.addTab(cluster_tab, "Cluster Config")
        tabs.addTab(monitor_tab, "Services to Monitor")
        tabs.addTab(gui_tab, "GUI Services")

        main_layout.addWidget(tabs)

        # --- Button ---
        self.encrypt_button = QPushButton('Generate and Save Config for Server')
        self.encrypt_button.clicked.connect(self.handle_encrypt_and_save)
        main_layout.addWidget(self.encrypt_button)

        self.setLayout(main_layout)

    def check_and_generate_keys(self):
        """
        Checks for keys. If missing, runs generator and returns False 
        to force a second button click.
        """
        if os.path.exists(PUBLIC_KEY_PATH) and os.path.exists(PRIVATE_KEY_PATH):
            return True  # Keys already exist, OK to proceed.

        reply = QMessageBox.question(self, "Keys Not Found", 
            "RSA keys not found. Do you want to generate them now?\n"
            f"Private key will be saved in: {SERVER_CONFIG_DIR}\n"
            f"Public key will be saved in: {SETUP_DIR}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)

        if reply == QMessageBox.Yes:
            try:
                # Run the key generator script
                subprocess.run([sys.executable, GENERATOR_SCRIPT_PATH], check=True, capture_output=True, text=True)
                
                # --- THIS IS THE FIX ---
                # Tell the user to click again and STOP the current function.
                QMessageBox.information(self, "Success", 
                    "Keys generated successfully.\n\n"
                    "Please click the 'Generate and Save' button AGAIN to create the encrypted file.")
                return False # This STOPS the handle_encrypt_and_save function
                # --- END OF FIX ---

            except subprocess.CalledProcessError as e:
                QMessageBox.critical(self, "Error", f"Failed to generate keys:\n{e.stderr}")
                return False
        else:
            # User clicked "No"
            return False

    def handle_encrypt_and_save(self):
        """Gathers data, encrypts it, and saves it to the server config folder."""
        
        if not self.check_and_generate_keys():
            QMessageBox.warning(self, "Cancelled", "Cannot encrypt data without RSA keys.")
            return

        try:
            # 1. Get .env data
            env_details = {
                "DB_SERVER": self.db_server_input.text(),
                "DB_DATABASE": self.db_name_input.text(),
                "DB_USERNAME": self.db_user_input.text(),
                "DB_PASSWORD": self.db_pass_input.text(),
            }

            # 2. Get and parse Cluster YAML
            cluster_yaml_str = self.cluster_text_edit.toPlainText()
            cluster_config = yaml.safe_load(cluster_yaml_str)
            if not isinstance(cluster_config, dict):
                raise yaml.YAMLError("'Cluster Config' must be a valid YAML dictionary.")

            # 3. Get and parse Services to Monitor YAML
            monitor_yaml_str = self.monitor_text_edit.toPlainText()
            services_to_monitor = yaml.safe_load(monitor_yaml_str)
            if not isinstance(services_to_monitor, list):
                raise yaml.YAMLError("'Services to Monitor' must be a valid YAML list.")

            # 4. Get and parse GUI Services YAML
            gui_yaml_str = self.gui_text_edit.toPlainText()
            services_gui = yaml.safe_load(gui_yaml_str)
            if not isinstance(services_gui, list):
                raise yaml.YAMLError("'GUI Services' must be a valid YAML list.")

            # 5. Combine all data
            all_data = {
                "env": env_details,
                "cluster": cluster_config,
                "services": services_to_monitor,
                "services_GUI": services_gui
            }

            # 6. Encrypt the data
            encrypted_output = encrypt_data(all_data, PUBLIC_KEY_PATH)

            # 7. Save the file directly
            os.makedirs(SERVER_CONFIG_DIR, exist_ok=True)
            with open(ENCRYPTED_CONFIG_PATH, 'w') as f:
                f.write(encrypted_output)
            
            QMessageBox.information(self, "Success", 
                f"Encrypted configuration saved to:\n{ENCRYPTED_CONFIG_PATH}\n\n"
                "You can now close this window. The server will continue loading.")
            
            # Close the GUI automatically on success
            self.close()

        except yaml.YAMLError as e:
            QMessageBox.critical(self, "YAML Error", f"Error parsing YAML input:\n{e}")
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Full encryption error traceback:\n{error_details}")
            QMessageBox.critical(self, "Error", f"An error occurred:\n{e}\n\nDetails:\n{error_details}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ConfigApp()
    ex.show()
    sys.exit(app.exec_())