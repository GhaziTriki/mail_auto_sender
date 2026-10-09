#!/usr/bin/env sh
# Prints a Fernet key suitable for SECRET_KEY.
python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
