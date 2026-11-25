"""Retrieve a password from KeePassXC without persisting it in app config.

Uses keepassxc-cli's `show -s -a password` command. The CLI prompts for the
database master password through the user's terminal. The NVR password is
captured only in process memory and is never logged.
"""
import shutil
import subprocess

class CredentialError(RuntimeError):
    pass

def get_keepass_password(database, entry, group=""):
    executable = shutil.which("keepassxc-cli")
    if not executable:
        raise CredentialError("keepassxc-cli was not found. Install KeePassXC.")
    database = str(database)
    entry_path = f"{group}/{entry}" if group else entry
    cmd = [executable, "show", "-s", "-a", "password", database, entry_path]
    try:
        # stdin remains attached to the terminal so keepassxc-cli can prompt.
        result = subprocess.run(
            cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False
        )
    except OSError as exc:
        raise CredentialError(f"Could not run keepassxc-cli: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "KeePassXC returned an error."
        raise CredentialError(detail)
    password = result.stdout.rstrip("\r\n")
    if not password:
        raise CredentialError("The KeePassXC entry returned an empty password.")
    return password
