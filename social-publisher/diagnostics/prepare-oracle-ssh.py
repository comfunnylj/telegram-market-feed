"""Normalize Windows text safely; never log secret material."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(os.environ['RUNNER_TEMP']) / 'sp-ssh'
root.mkdir(mode=0o700, parents=True, exist_ok=True)
for env, name in [('ORACLE_KEY', 'key'), ('ORACLE_HOST_KEYS', 'known_hosts')]:
    value = os.environ[env].lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n').strip()
    if '\n' not in value and '\\n' in value:
        value = value.replace('\\r\\n', '\n').replace('\\n', '\n')
    target = root / name
    target.write_text(value + '\n')
    target.chmod(0o600)
probe = subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', str(root / 'key')], capture_output=True)
if probe.returncode:
    reason = 'encrypted_key_requires_passphrase' if b'passphrase' in probe.stderr.lower() else 'invalid_private_key_format'
    print('SSH key validation: ' + reason + '. No secret material logged.')
    sys.exit(1)
print('SSH private key format validated; secret material withheld.')
