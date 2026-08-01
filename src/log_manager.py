import asyncio
import re
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from alerts_service import AlertsService


class LogManager:
    def __init__(self):
        self.message_patterns: Dict = {}
        self.seen_messages: set = set()
        self.log_buffer = deque(maxlen=1000)
        self.lock = asyncio.Lock()
        self.last_cleanup_state = None
        self.alerts_service = AlertsService()

    async def process_log_entry(self, log_entry: str) -> Optional[Dict]:
        async with self.lock:
            match = re.match(r"(\w+ \d+ \d+:\d+:\d+) \S+ (.+)", log_entry)
            if not match:
                return None

            timestamp, message = match.groups()

            try:
                parsed_time = datetime.strptime(timestamp, '%b %d %H:%M:%S')
                parsed_time = parsed_time.replace(year=datetime.now().year)
            except ValueError:
                return None

            pattern = self.get_message_pattern(message)
            group_key = f"{pattern}:{parsed_time.strftime('%Y%m%d%H%M')}"

            if "WAIT_FOR_CLEANUP" in message:
                current_state = {
                    'timestamp': timestamp,
                    'parsed_time': parsed_time,
                    'message': message
                }
                if not self.last_cleanup_state or \
                   self.last_cleanup_state['timestamp'] != timestamp:
                    self.last_cleanup_state = current_state
                else:
                    return None

            return {
                'timestamp': timestamp,
                'datetime': parsed_time.isoformat(),
                'message': message,
                'raw': log_entry,
                'pattern': pattern,
                'group_key': group_key
            }

    async def process_logs(self, logs: List[str]) -> List[Dict]:
        processed_groups = {}

        for log_entry in logs:
            entry = await self.process_log_entry(log_entry)
            if entry:
                if entry['group_key'] not in processed_groups:
                    processed_groups[entry['group_key']] = entry

        result = []
        for entry in processed_groups.values():
            base_message = self.get_base_message(entry['raw'])

            msg_type = 'info'
            alert_data = None

            if 'WAR' in base_message:
                msg_type = 'warning'
            elif 'ERR' in base_message:
                msg_type = 'error'

            sanitized_base = self.sanitize_message(base_message)

            if 'WAIT_FOR_CLEANUP' in base_message:
                alert_data = {
                    'type': 'info',
                    'message': 'Build Complete',
                    'details': {
                        'raw_message': f"Build has completed and is waiting for cleanup at {entry['timestamp']}",
                        'timestamp': entry['timestamp']
                    }
                }
            elif 'SystemService' in base_message and 'Scheduling next check for updates' in base_message:
                update_match = re.search(r'Scheduling next check for updates in (\d+\.\d+) minute', base_message)
                if update_match:
                    minutes = float(update_match.group(1))
                    next_check = datetime.now() + timedelta(minutes=minutes)
                    time_string = next_check.strftime('%H:%M:%S')
                    alert_data = {
                        'type': 'info',
                        'message': 'System Updates',
                        'details': {
                            'raw_message': f"Next update check scheduled for {time_string}",
                            'timestamp': entry['timestamp']
                        }
                    }
            elif 'StardustService' in base_message and 'Connection stopped working' in base_message:
                fail_match = re.search(r'fail_reason: ([^)]+)', base_message)
                fail_reason = fail_match.group(1) if fail_match else 'unknown reason'
                alert_data = {
                    'type': 'warning',
                    'message': 'Stardust Service',
                    'details': {
                        'raw_message': f"Stardust service connection issues. Error: {fail_reason}",
                        'timestamp': entry['timestamp']
                    }
                }
            elif msg_type in ['warning', 'error']:
                alert_data = {
                    'type': msg_type,
                    'message': sanitized_base.split(' - ', 1)[0] if ' - ' in sanitized_base else sanitized_base,
                    'details': {
                        'raw_message': sanitized_base,
                        'timestamp': entry['timestamp']
                    }
                }

            if alert_data:
                await self.alerts_service.process_alert(alert_data)

            sanitized_message = self.sanitize_message(base_message)
            sanitized_raw = self.sanitize_message(entry['raw'])

            formatted_entry = {
                'timestamp': entry['timestamp'],
                'datetime': entry['datetime'],
                'message': sanitized_message,
                'type': msg_type,
                'occurrences': 1,
                'raw': sanitized_raw
            }
            result.append(formatted_entry)

        result.sort(key=lambda x: x['datetime'], reverse=True)
        return result

    SENSITIVE_PATTERNS = [
        (r"'password':\s*'[^']*'", "'password': '[REDACTED]'"),
        (r"'api_key':\s*'[^']*'", "'api_key': '[REDACTED]'"),
        (r"'token':\s*'[^']*'", "'token': '[REDACTED]'"),
        (r"'secret':\s*'[^']*'", "'secret': '[REDACTED]'"),
    ]

    @classmethod
    def sanitize_message(cls, message: str) -> str:
        for pattern, replacement in cls.SENSITIVE_PATTERNS:
            message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)
        return message

    def get_base_message(self, message: str) -> str:
        match = re.match(r"\w+ \d+ \d+:\d+:\d+ \S+ (.+)", message)
        if not match:
            return message
        base_msg = match.group(1)
        if 'MJPG-streamer' in base_msg and 'serving client' in base_msg:
            base_msg = re.sub(r'\n\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', '', base_msg)
        return base_msg

    def get_message_pattern(self, message: str) -> str:
        pattern = re.sub(r'\d{2}:\d{2}:\d{2}', 'TIME', message)
        pattern = re.sub(r'\d+\.\d+', 'NUM', pattern)
        pattern = re.sub(r'\d+', 'NUM', pattern)
        pattern = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID', pattern)
        pattern = re.sub(r'0x[0-9a-f]+', 'HEX', pattern)
        return pattern

    def get_recent_logs(self, limit: int = 100) -> List[Dict]:
        return list(self.log_buffer)[-limit:]

    async def clear_old_data(self):
        current_time = datetime.now()
        self.message_patterns = {
            k: v for k, v in self.message_patterns.items()
            if (current_time - v.get('parsed_time', current_time)).total_seconds() < 3600
        }

        if self.last_cleanup_state:
            try:
                time_diff = (current_time - self.last_cleanup_state['parsed_time']).total_seconds()
                if time_diff > 300:
                    self.last_cleanup_state = None
            except (ValueError, TypeError, KeyError):
                self.last_cleanup_state = None

        if len(self.seen_messages) > 10000:
            self.seen_messages.clear()
            self.seen_messages.update(log['raw'] for log in self.log_buffer)

        if len(self.message_patterns) > 1000:
            recent_patterns = {log['pattern'] for log in self.log_buffer}
            self.message_patterns = {
                k: v for k, v in self.message_patterns.items()
                if k in recent_patterns
            }

        await self.alerts_service.clear_old_alerts()
