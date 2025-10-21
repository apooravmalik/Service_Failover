# server/config/decrypt.py
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

def decrypt_data(encrypted_payload_str, private_key_path):
    """
    Decrypts large data using hybrid encryption (RSA + Fernet/AES).
    """
    try:
        # 1. Load private key
        with open(private_key_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(), 
                password=None, 
                backend=default_backend()
            )

        # 2. Decode the payload from string to bytes
        encrypted_payload_bytes = encrypted_payload_str.encode('utf-8')

        # 3. Split the payload into its two parts
        b64_rsa_encrypted_key, fernet_encrypted_data = encrypted_payload_bytes.split(b":", 1)

        # 4. Decode the RSA-encrypted key part
        rsa_encrypted_key = base64.b64decode(b64_rsa_encrypted_key)

        # 5. Decrypt the *symmetric key* with the RSA private key
        fernet_key = private_key.decrypt(
            rsa_encrypted_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # 6. Create the Fernet object and decrypt the large data
        f = Fernet(fernet_key)
        decrypted_data_bytes = f.decrypt(fernet_encrypted_data)

        # 7. Decode bytes to JSON string and load
        decrypted_data_str = decrypted_data_bytes.decode('utf-8')
        return json.loads(decrypted_data_str)

    except Exception as e:
        raise Exception(f"Decryption failed. Data may be corrupt or key is wrong. Error: {e}")