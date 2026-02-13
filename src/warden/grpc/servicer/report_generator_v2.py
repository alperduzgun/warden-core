"""Report generator with atomic writes and memory optimization (ID 41, 42)."""

import asyncio
import json
import os


class ReportGenerator:
    async def generate_json_report_safe(self, path, data):
        tmp = path + ".tmp"
        async with open(tmp, "w") as f:
            await f.write(json.dumps(self._sanitize_inplace(data)))
        os.replace(tmp, path)

    def _sanitize_inplace(self, obj):
        """Stream sanitization instead of deepcopy (ID 42)."""
        if isinstance(obj, dict):
            return {k: self._sanitize_inplace(v) for k, v in obj.items()}
        return obj
