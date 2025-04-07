import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

class EventLogService:
    def __init__(self, base_url: str = "http://192.168.6.218"):
        self.base_url = base_url
        self.events_endpoint = f"{base_url}/api/v1/history/events"

    def get_events(self, count: Optional[int] = None) -> List[Dict[Any, Any]]:
        """
        Fetch events from the API endpoint
        Args:
            count: Optional number of events to retrieve
        Returns a list of event dictionaries
        """
        try:
            url = self.events_endpoint
            if count is not None:
                url = f"{url}?count={count}"
                
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching events: {e}")
            return []

    def format_event_time(self, time_str: str) -> str:
        """
        Format the event time string to a more readable format
        """
        try:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return time_str

    def get_formatted_events(self, count: Optional[int] = None) -> List[Dict[Any, Any]]:
        """
        Get events with formatted timestamps
        Args:
            count: Optional number of events to retrieve
        """
        events = self.get_events(count)
        for event in events:
            if 'time' in event:
                event['formatted_time'] = self.format_event_time(event['time'])
        return events 