"""File locking for concurrent writes (ID 26)."""

import asyncio
import fcntl
import os


class FileLockManager:
    async def atomic_write(self, path, content):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(content)
        os.replace(tmp, path)
