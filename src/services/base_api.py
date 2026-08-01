from typing import Optional

from logger import logger
from printer_client import get_printer_session


class PrinterApiService:
    def __init__(self, base_url: str = "", api_key: str = None,
                 auth_username: str = None, auth_password: str = None):
        self.base_url = base_url
        self.api_key = api_key
        self.auth_username = auth_username
        self.auth_password = auth_password

    async def _fetch(self, endpoint: str, count: Optional[int] = None) -> list:
        url = f"{self.base_url}{endpoint}"
        if count is not None:
            url = f"{url}?count={count}"

        try:
            session = await get_printer_session()
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning("Error fetching %s: status %s", endpoint, response.status)
                return []
        except Exception:
            logger.exception("Error fetching %s", endpoint)
            return []
