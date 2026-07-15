from __future__ import annotations

import logging
import re

import aiohttp


logger = logging.getLogger("mitra.dialer_calls")

DIALER_TIMEOUT_SECONDS = 20
DEFAULT_COUNTRY_CODE = "91"


class DialerCallError(Exception):
    pass


_CALL_ID_TAIL = re.compile(r"(\d{6,}\.\d+)")


def transfer_call_id_candidates(raw: str) -> list[str]:
    """Acefone's originate returns an id like 'SRVINF-...-1784024931.428712' but
    the /call/options transfer expects the 'epoch.channel' tail. Return the tail
    first, then the raw id as a fallback."""
    raw = str(raw or "").strip()
    candidates: list[str] = []
    match = _CALL_ID_TAIL.search(raw)
    if match:
        candidates.append(match.group(1))
    if raw and raw not in candidates:
        candidates.append(raw)
    return candidates


def normalize_msisdn(number: str) -> str:
    """Acefone expects country-code-prefixed numbers (e.g. 918065139919)."""
    digits = "".join(ch for ch in str(number or "") if ch.isdigit())
    if not digits:
        return ""
    if len(digits) == 10:
        return DEFAULT_COUNTRY_CODE + digits
    if len(digits) == 11 and digits.startswith("0"):
        return DEFAULT_COUNTRY_CODE + digits[1:]
    return digits


class DialerCallClient:
    """Client for the Acefone dialer used by the "Human Agent" preference.

    Two-step flow:
      1. click_to_call_support -> rings the driver (customer).
      2. call/options (type=4, transfer) -> connects the human agent (intercom)
         into the active call. This needs the active call_id.
    """

    def __init__(
        self,
        api_key: str,
        api_url: str,
        api_token: str,
        transfer_url: str,
        caller_id: str = "",
        bridge_url: str = "",
    ) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.api_token = api_token
        self.transfer_url = transfer_url
        self.bridge_url = bridge_url
        self.caller_id = normalize_msisdn(caller_id) if caller_id else ""

    async def place_bridge_call(self, agent_number: str, destination_number: str) -> dict:
        """Bridge two phones directly via /v1/click_to_call (Bearer auth).

        Acefone rings the agent and the destination and connects them.
        """
        if not self.api_token:
            raise DialerCallError("DIALER_API_TOKEN is not configured for the bridge call")
        if not self.bridge_url:
            raise DialerCallError("DIALER_BRIDGE_URL is not configured")
        agent = normalize_msisdn(agent_number)
        destination = normalize_msisdn(destination_number)
        if not agent or not destination:
            raise DialerCallError("Both agent and driver numbers are required for the bridge")
        if agent == destination:
            # Acefone cannot bridge a number to itself; surface it clearly.
            raise DialerCallError(
                "Agent and driver numbers are identical; set a distinct HUMAN_AGENT_NUMBER to bridge"
            )

        payload = {
            "agent_number": agent,
            "destination_number": destination,
        }
        if self.caller_id:
            payload["caller_id"] = self.caller_id
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_token}",
        }
        logger.info("dialer_call.bridge agent=%s destination=%s caller_id=%s", agent, destination, self.caller_id or "-")
        data = await self._post(self.bridge_url, payload, headers)
        success = data.get("success", data.get("Success"))
        message = data.get("message", data.get("Message", ""))
        logger.info("dialer_call.bridge.done agent=%s success=%s message=%s", agent, success, message)
        if success is False:
            raise DialerCallError(f"Bridge call refused: {message or 'unknown error'}")
        return {"success": success, "message": message, "raw": data}

    async def place_support_call(self, customer_number: str, custom_identifier: str = "") -> dict:
        if not self.api_key:
            raise DialerCallError("DIALER_API_KEY is not configured")
        if not customer_number:
            raise DialerCallError("Missing driver number for the dialer call")
        customer_number = normalize_msisdn(customer_number)

        payload: dict = {
            "customer_number": customer_number,
            "api_key": self.api_key,
            "async": 1,
            # Best-effort: some Acefone accounts return a call id when this is set.
            "get_call_id": 1,
        }
        if self.caller_id:
            payload["caller_id"] = self.caller_id
        if custom_identifier:
            payload["custom_identifier"] = custom_identifier

        headers = {"accept": "application/json", "content-type": "application/json"}
        logger.info("dialer_call.support number=%s caller_id=%s", customer_number, self.caller_id or "-")
        data = await self._post(self.api_url, payload, headers)

        # call_id may or may not be present depending on account config.
        call_id = data.get("call_id") or data.get("callId") or data.get("uuid")
        success = data.get("Success", data.get("success"))
        message = data.get("Message", data.get("message", ""))
        logger.info(
            "dialer_call.support.done number=%s success=%s call_id=%s message=%s",
            customer_number,
            success,
            call_id,
            message,
        )
        if success is False:
            raise DialerCallError(f"Dialer refused the call: {message or 'unknown error'}")
        return {"success": success, "message": message, "call_id": call_id, "raw": data}

    async def transfer_to_agent(self, call_id: str, intercom: str) -> dict:
        if not self.api_token:
            raise DialerCallError("DIALER_API_TOKEN is not configured for transfer")
        if not call_id:
            raise DialerCallError("No active call_id available to transfer")
        if not intercom:
            raise DialerCallError("Missing human agent number for transfer")
        intercom = normalize_msisdn(intercom)

        payload = {"type": "4", "call_id": call_id, "intercom": intercom}
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_token}",
        }
        logger.info("dialer_call.transfer call_id=%s intercom=%s", call_id, intercom)
        data = await self._post(self.transfer_url, payload, headers)
        success = data.get("success", data.get("Success"))
        message = data.get("message", data.get("Message", ""))
        if success is False:
            raise DialerCallError(f"Transfer failed: {message or 'unknown error'}")
        return {"success": success, "message": message, "raw": data}

    async def _post(self, url: str, payload: dict, headers: dict) -> dict:
        timeout = aiohttp.ClientTimeout(total=DIALER_TIMEOUT_SECONDS)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    text = await response.text()
                    if response.status >= 400:
                        raise DialerCallError(f"Dialer HTTP {response.status}: {text[:500]}")
                    try:
                        return await response.json(content_type=None)
                    except Exception as exc:  # noqa: BLE001 - normalize into DialerCallError
                        raise DialerCallError(f"Dialer returned non-JSON response: {text[:500]}") from exc
        except aiohttp.ClientError as exc:
            raise DialerCallError(f"Dialer connection failed: {exc}") from exc
