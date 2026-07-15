from __future__ import annotations

import logging

import aiohttp


logger = logging.getLogger("mitra.dhwani_calls")

CALL_TIMEOUT_SECONDS = 20


class DhwaniCallError(Exception):
    pass


class DhwaniCallClient:
    """Thin client for the Dhwani outbound calls REST API.

    POST {base_url}/api/v1/calls/{number}/
      Authorization: Bearer <api_key>
      { "agent": ..., "receiver_name": ..., "user_instructions": ... }
    """

    def __init__(self, api_key: str, base_url: str, agent: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.agent = agent or "default"

    async def place_call(
        self,
        number: str,
        receiver_name: str,
        user_instructions: str,
    ) -> dict:
        if not self.api_key:
            raise DhwaniCallError("DHWANI_CALL_API_KEY is not configured")
        if not number:
            raise DhwaniCallError("Missing phone number for the healthcare call")

        url = f"{self.base_url}/api/v1/calls/{number}/"
        payload = {
            "agent": self.agent,
            "receiver_name": receiver_name or "Driver",
            "user_instructions": user_instructions or "",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info("dhwani_call.place number=%s agent=%s", number, self.agent)
        timeout = aiohttp.ClientTimeout(total=CALL_TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    text = await response.text()
                    if response.status >= 400:
                        detail = text[:500]
                        raise DhwaniCallError(f"Dhwani HTTP {response.status}: {detail}")
                    try:
                        data = await response.json(content_type=None)
                    except Exception as exc:  # noqa: BLE001 - normalize into DhwaniCallError
                        raise DhwaniCallError(f"Dhwani returned non-JSON response: {text[:500]}") from exc
        except aiohttp.ClientError as exc:
            raise DhwaniCallError(f"Dhwani connection failed: {exc}") from exc

        call_id = data.get("call_id")
        status = data.get("status")
        logger.info("dhwani_call.queued number=%s call_id=%s status=%s", number, call_id, status)
        return {"call_id": call_id, "status": status, "raw": data}
