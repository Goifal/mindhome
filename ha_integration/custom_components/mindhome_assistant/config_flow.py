"""Config flow fuer MindHome Assistant."""

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_URL

from . import DOMAIN

DEFAULT_URL = "http://192.168.1.200:8200"


class MindHomeAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow fuer MindHome Assistant."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            api_key = user_input.get(CONF_API_KEY, "").strip()

            # Verbindung testen (Health-Endpoint braucht keinen API Key)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{url}/api/assistant/health",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") in ("ok", "degraded"):
                                # API Key testen (Chat-Endpoint braucht Key)
                                if api_key:
                                    headers = {"X-API-Key": api_key}
                                    async with session.get(
                                        f"{url}/api/assistant/settings",
                                        headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=5),
                                    ) as key_resp:
                                        if key_resp.status == 403:
                                            errors["base"] = "invalid_api_key"
                                        elif key_resp.status == 200:
                                            return self.async_create_entry(
                                                title="MindHome Assistant",
                                                data={"url": url, "api_key": api_key},
                                            )
                                else:
                                    return self.async_create_entry(
                                        title="MindHome Assistant",
                                        data={"url": url, "api_key": ""},
                                    )
                        if "base" not in errors:
                            errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default=DEFAULT_URL): str,
                vol.Optional(CONF_API_KEY, default=""): str,
            }),
            errors=errors,
        )
