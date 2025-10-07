# communication.py

import socket
import json
import logging
import threading

logger = logging.getLogger(__name__)

class MessageHandler:
    def __init__(self, host, port, callback):
        self.host = host
        self.port = port
        self.callback = callback
        self.server_socket = None
        self.is_running = False

    def start_server(self):
        self.is_running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        logger.info(f"Server listening on {self.host}:{self.port}")

        while self.is_running:
            try:
                client_socket, addr = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client_socket, addr)).start()
            except OSError:
                # This will happen when the socket is closed, which is expected.
                break
            except Exception as e:
                if self.is_running:
                    logger.error(f"Error accepting connection: {e}")

    def handle_client(self, client_socket, addr):
        try:
            with client_socket:
                data = client_socket.recv(4096)
                if data:
                    message = json.loads(data.decode('utf-8'))
                    logger.debug(f"Received message from {addr}: {message}")
                    if self.callback:
                        self.callback(message)
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON from message.")
        except Exception as e:
            logger.error(f"Error handling client {addr}: {e}")

    def stop_server(self):
        self.is_running = False
        if self.server_socket:
            self.server_socket.close()
        logger.info("Server stopped.")

    @staticmethod
    def send_message(host, port, message):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((host, port))
                sock.sendall(json.dumps(message).encode('utf-8'))
                logger.debug(f"Sent message to {host}:{port}: {message}")
                return True
        except socket.timeout:
            logger.warning(f"Connection to {host}:{port} timed out.")
            return False
        except ConnectionRefusedError:
            logger.warning(f"Connection to {host}:{port} was refused.")
            return False
        except Exception as e:
            logger.error(f"Failed to send message to {host}:{port}: {e}")
            return False