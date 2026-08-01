from datetime import datetime
from typing import Optional

from services.base_api import PrinterApiService


class EventLogService(PrinterApiService):
    def __init__(self, base_url: str = "", api_key: str = None,
                 auth_username: str = None, auth_password: str = None):
        super().__init__(base_url, api_key, auth_username, auth_password)
        self.events_endpoint = "/api/v1/history/events"

    async def get_events(self, count: Optional[int] = None) -> list:
        return await self._fetch(self.events_endpoint, count)

    def format_event_time(self, time_str: str) -> str:
        try:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return time_str

    async def get_formatted_events(self, count: Optional[int] = None) -> list:
        events = await self.get_events(count)
        for event in events:
            if 'time' in event:
                event['formatted_time'] = self.format_event_time(event['time'])
        return events
