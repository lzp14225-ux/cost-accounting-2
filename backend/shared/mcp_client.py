import asyncio
import json
import logging
import os
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class MCPClient:
    def __init__(
        self,
        base_url: str,
        timeout: int | None = None,
        pool_size: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or int(os.getenv("MCP_CLIENT_TIMEOUT", "300"))
        pool_size = pool_size or int(os.getenv("MCP_CLIENT_POOL_SIZE", "30"))
        max_retries = max_retries or int(os.getenv("MCP_CLIENT_MAX_RETRIES", "3"))

        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"],
        )
        adapter = HTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            max_retries=retry_strategy,
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        logger.info(
            "MCP Client initialized: %s, timeout=%ss, pool=%s, retries=%s",
            self.base_url,
            self.timeout,
            pool_size,
            max_retries,
        )

    async def call_tool(self, server_name: str, tool_name: str, payload: dict[str, Any]):
        if not self.base_url:
            raise RuntimeError("MCP base_url is empty")

        logger.info("Calling MCP tool: %s.%s", server_name, tool_name)
        logger.debug("Arguments: %s", payload)
        result = await self._call_tool_direct(tool_name, payload)

        if result.get("status") == "error":
            detail = result.get("detail") or result.get("message") or "unknown error"
            raise RuntimeError(f"Unable to call MCP tool {tool_name} on {self.base_url}: {detail}")

        return result

    async def _call_tool_direct(self, tool_name: str, arguments: dict[str, Any]):
        import time

        start_time = time.time()
        url = f"{self.base_url}/call_tool"
        request_body = {
            "tool_name": tool_name,
            "arguments": arguments,
        }

        logger.debug("Sending request: %s", url)
        logger.debug("Body: %s", json.dumps(request_body, ensure_ascii=False))

        try:
            response = await asyncio.to_thread(
                self.session.post,
                url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info("Tool call success: %s (%sms)", tool_name, duration_ms)
            return result
        except requests.HTTPError as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "HTTP error: %s - %s (%sms)",
                exc.response.status_code,
                exc.response.text,
                duration_ms,
            )
            return {
                "status": "error",
                "message": f"HTTP error: {exc.response.status_code}",
                "detail": exc.response.text,
            }
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error("Tool call failed: %s (%sms)", exc, duration_ms, exc_info=True)
            return {
                "status": "error",
                "message": f"Tool call failed: {str(exc)}",
            }

    async def close(self):
        if hasattr(self, "session") and self.session:
            self.session.close()
        logger.info("MCP client closed")
