"""Initialize the mounted disk, then drop privileges before serving requests."""
import os
import pwd
from pathlib import Path

os.umask(0o077)
directory = Path('/app/data')
directory.mkdir(parents=True, exist_ok=True)
account = pwd.getpwnam('robot')
os.chown(directory, account.pw_uid, account.pw_gid)
os.setgroups([])
os.setgid(account.pw_gid)
os.setuid(account.pw_uid)
os.execvp('python', ['python', 'server.py'])
