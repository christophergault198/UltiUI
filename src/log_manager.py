from datetime import datetime
import re
from typing import Dict, List, Set, Optional
import asyncio
from collections import deque
from operator import itemgetter
import hashlib
from alerts_service import AlertsService

class LogManager:
    def __init__(self):
        self.message_patterns = {}  # Track message patterns and their variations
        self.seen_messages = set()  # Track unique messages
        self.log_buffer = deque(maxlen=1000)  # Store last 1000 processed logs
        self.lock = asyncio.Lock()  # Thread safety for log processing
        self.last_cleanup_state = None  # Track the last cleanup state
        self.alerts_service = AlertsService()  # Initialize alerts service
        
    async def process_log_entry(self, log_entry: str) -> Optional[Dict]:
        """Process a single log entry and return structured data"""
        async with self.lock:
            # Extract timestamp and message parts
            match = re.match(r"(\w+ \d+ \d+:\d+:\d+) \S+ (.+)", log_entry)
            if not match:
                return None
                
            timestamp, message = match.groups()
            
            # Parse timestamp for sorting
            try:
                parsed_time = datetime.strptime(timestamp, '%b %d %H:%M:%S')
                # Add current year since logs don't include it
                parsed_time = parsed_time.replace(year=datetime.now().year)
            except ValueError:
                return None

            # Create message pattern for grouping
            pattern = self.get_message_pattern(message)
            
            # Create unique key for this message group
            # Include minute in key to group messages within same minute
            group_key = f"{pattern}:{parsed_time.strftime('%Y%m%d%H%M')}"
            
            # Special handling for cleanup messages
            if "WAIT_FOR_CLEANUP" in message:
                current_state = {
                    'timestamp': timestamp,
                    'parsed_time': parsed_time,
                    'message': message
                }
                
                # Only process if this is a new cleanup state or significant time has passed
                if not self.last_cleanup_state or \
                   self.last_cleanup_state['timestamp'] != timestamp:
                    self.last_cleanup_state = current_state
                else:
                    return None
            
            return {
                'timestamp': timestamp,
                'message': message,
                'raw': log_entry,
                'pattern': pattern,
                'group_key': group_key
            }

    async def process_logs(self, logs: List[str]) -> List[Dict]:
        """Process a list of log entries and return structured data"""
        processed_entries = []
        processed_groups = {}

        for log_entry in logs:
            entry = await self.process_log_entry(log_entry)
            if entry:
                # Use group_key to deduplicate similar messages within the same minute
                if entry['group_key'] not in processed_groups:
                    processed_groups[entry['group_key']] = entry

        result = []
        for entry in processed_groups.values():
            # Get the base message without variable parts
            base_message = self.get_base_message(entry['raw'])
            
            # Determine message type
            msg_type = 'info'
            if 'WAR' in base_message:
                msg_type = 'warning'
            elif 'ERR' in base_message:
                msg_type = 'error'
            
            # Format the entry
            formatted_entry = {
                'timestamp': entry['timestamp'],
                'message': base_message,
                'type': msg_type,
                'occurrences': 1,
                'raw': entry['raw']
            }
            
            # Process alert if it's a warning or error
            if msg_type in ['warning', 'error']:
                alert_id = hashlib.md5(f"{base_message}:{entry['timestamp']}".encode()).hexdigest()
                alert_data = {
                    'id': alert_id,
                    'type': msg_type,
                    'message': base_message,
                    'details': {
                        'timestamp': entry['timestamp'],
                        'raw_message': entry['raw']
                    }
                }
                await self.alerts_service.process_alert(alert_data)
            
            result.append(formatted_entry)
        
        # Sort by parsed timestamp, newest first
        result.sort(key=lambda x: datetime.strptime(x['timestamp'], '%b %d %H:%M:%S'), reverse=True)
        
        return result
    
    def get_base_message(self, message: str) -> str:
        """Get the base message without variable parts"""
        # Extract timestamp and actual message
        match = re.match(r"\w+ \d+ \d+:\d+:\d+ \S+ (.+)", message)
        if not match:
            return message
            
        base_msg = match.group(1)
        
        # Handle special cases
        if 'MJPG-streamer' in base_msg and 'serving client' in base_msg:
            # Remove duplicate IP addresses
            base_msg = re.sub(r'\n\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', '', base_msg)
        
        return base_msg
    
    def get_message_details(self, raw_messages: List[str]) -> Optional[List[str]]:
        """Extract relevant details from a group of messages"""
        if not raw_messages:
            return None
            
        # Get unique IP addresses for MJPG-streamer messages
        if 'MJPG-streamer' in raw_messages[0] and 'serving client' in raw_messages[0]:
            ips = set()
            for msg in raw_messages:
                ip_match = re.search(r'serving client: (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', msg)
                if ip_match:
                    ips.add(ip_match.group(1))
            if ips:
                return [f"Clients: {', '.join(sorted(ips))}"]
        
        # Extract error details for warning messages
        elif 'Failed to fetch' in raw_messages[0]:
            urls = set()
            for msg in raw_messages:
                url_match = re.search(r'Failed to fetch .+ at (http[^\s]+)', msg)
                if url_match:
                    urls.add(url_match.group(1))
            if urls:
                return [f"Failed endpoints: {', '.join(sorted(urls))}"]
        
        return None
    
    def get_message_pattern(self, message: str) -> str:
        """Extract a pattern from the message by replacing variable parts with placeholders"""
        # Replace timestamps
        pattern = re.sub(r'\d{2}:\d{2}:\d{2}', 'TIME', message)
        # Replace numbers
        pattern = re.sub(r'\d+\.\d+', 'NUM', pattern)
        pattern = re.sub(r'\d+', 'NUM', pattern)
        # Replace UUIDs and other hex strings
        pattern = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID', pattern)
        pattern = re.sub(r'0x[0-9a-f]+', 'HEX', pattern)
        return pattern
    
    def get_recent_logs(self, limit: int = 100) -> List[Dict]:
        """Get the most recent processed logs"""
        return list(self.log_buffer)[-limit:]
    
    async def clear_old_data(self):
        """Clear old data from tracking structures"""
        current_time = datetime.now()
        # Clear message patterns older than 1 hour
        self.message_patterns = {
            k: v for k, v in self.message_patterns.items()
            if (current_time - v.get('parsed_time', current_time)).total_seconds() < 3600
        }
        
        # Clear last cleanup state if it's older than 5 minutes
        if self.last_cleanup_state:
            try:
                time_diff = (current_time - self.last_cleanup_state['parsed_time']).total_seconds()
                if time_diff > 300:  # 5 minutes
                    self.last_cleanup_state = None
            except (ValueError, TypeError, KeyError):
                self.last_cleanup_state = None
        
        if len(self.seen_messages) > 10000:
            self.seen_messages.clear()
            self.seen_messages.update(log['raw'] for log in self.log_buffer)
        
        if len(self.message_patterns) > 1000:
            # Keep only patterns that have been seen in the last 1000 logs
            recent_patterns = {log['pattern'] for log in self.log_buffer}
            self.message_patterns = {
                k: v for k, v in self.message_patterns.items() 
                if k in recent_patterns
            }
            
        # Clear old alerts
        await self.alerts_service.clear_old_alerts() 