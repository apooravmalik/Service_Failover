# GUI/crypto.py
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

def encrypt_data(data_dict, public_key_path):
    """
    Encrypts large data using hybrid encryption (RSA + Fernet/AES).
    """
    try:
        # 1. Load RSA public key
        with open(public_key_path, "rb") as key_file:
            public_key = serialization.load_pem_public_key(
                key_file.read(), 
                backend=default_backend()
            )

        # 2. Convert data to bytes
        data_bytes = json.dumps(data_dict).encode('utf-8')

        # 3. Generate a new symmetric key (Fernet)
        fernet_key = Fernet.generate_key()
        f = Fernet(fernet_key)

        # 4. Encrypt the large data with the symmetric key
        #    (fernet_encrypted_data is already url-safe base64)
        fernet_encrypted_data = f.encrypt(data_bytes)

        # 5. Encrypt the *symmetric key* with the RSA public key
        rsa_encrypted_key = public_key.encrypt(
            fernet_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # 6. Base64 encode the RSA-encrypted key for safe transport
        b64_rsa_encrypted_key = base64.b64encode(rsa_encrypted_key)

        # 7. Join the two parts with a unique delimiter.
        #    We'll return a single string: [key_part]:[data_part]
        final_payload = b64_rsa_encrypted_key + b":" + fernet_encrypted_data
        
        # Return as a single utf-8 string
        return final_payload.decode('utf-8')

    except Exception as e:
        # Pass the original error up
        raise Exception(f"Encryption failed: {e}")