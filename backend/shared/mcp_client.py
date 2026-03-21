import httpx


class MCPClient:
    def __init__(self, base_url: str, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def call_tool(self, server_name: str, tool_name: str, payload: dict):
        if not self.base_url:
            raise RuntimeError("MCP base_url is empty")

        request_body = {
            "server": server_name,
            "tool": tool_name,
            "arguments": payload,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for path in ("/tool/call", "/tools/call", "/call_tool"):
                try:
                    response = await client.post(f"{self.base_url}{path}", json=request_body)
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPError:
                    continue

        raise RuntimeError(f"Unable to call MCP tool {tool_name} on {self.base_url}")
