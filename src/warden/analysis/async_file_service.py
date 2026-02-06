"""Async file I/O (ID 13)."""
import aiofiles
async def read_file_async(path):
    async with aiofiles.open(path) as f:
        return await f.read()
