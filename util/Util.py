from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def create_bastion_to_private_keypair():
    private_key_object = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    public_key_string = private_key_object.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                                                      serialization.PublicFormat.OpenSSH)
    private_key_string = private_key_object.private_bytes(serialization.Encoding.PEM,
                                                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

    return {'public': public_key_string.decode('utf-8'), 'private': private_key_string.decode('utf-8')}
