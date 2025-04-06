from datetime import datetime
import re
from typing import Dict, List, Set, Optional
import asyncio
from collections import deque
from operator import itemgetter

class LogManager:
    def __init__(self):
        self.message_patterns = {}  # Track message patterns and their variations
        self.seen_messages = set()  # Track unique messages
        self.active_alerts = {}  # Store active alerts
        self.log_buffer = deque(maxlen=1000)  # Store last 1000 processed logs
        self.lock = asyncio.Lock()  # Thread safety for log processing
        
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
            
            # Get or create message group
            if group_key in self.message_patterns:
                group = self.message_patterns[group_key]
                group['count'] += 1
                group['last_timestamp'] = timestamp
                group['raw_messages'].append(log_entry)
            else:
                group = {
                    'pattern': pattern,
                    'count': 1,
                    'first_timestamp': timestamp,
                    'last_timestamp': timestamp,
                    'raw_messages': [log_entry],
                    'parsed_time': parsed_time
                }
                self.message_patterns[group_key] = group
            
            return group

    async def process_logs(self, logs: List[str]) -> List[Dict]:
        """Process multiple log entries and return structured data"""
        processed_groups = {}
        
        # Process each log entry
        for log_entry in logs:
            group = await self.process_log_entry(log_entry)
            if group:
                group_key = f"{group['pattern']}:{group['parsed_time'].strftime('%Y%m%d%H%M')}"
                processed_groups[group_key] = group
        
        # Convert groups to list and sort by timestamp
        result = []
        for group in processed_groups.values():
            # Get the base message without variable parts
            base_message = self.get_base_message(group['raw_messages'][0])
            
            # Determine message type
            msg_type = 'info'
            if 'WAR' in base_message:
                msg_type = 'warning'
            elif 'ERR' in base_message:
                msg_type = 'error'
            
            # Format the entry
            entry = {
                'timestamp': group['first_timestamp'],
                'message': base_message,
                'type': msg_type,
                'occurrences': group['count'],
                'raw': group['raw_messages'][0],  # Keep first raw message for reference
                'details': self.get_message_details(group['raw_messages'])
            }
            result.append(entry)
        
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
        """Extract a pattern from a message for grouping similar messages"""
        # Remove timestamp and hostname
        message = re.sub(r'^\w+ \d+ \d+:\d+:\d+ \S+ ', '', message)
        
        # Extract service name and message type
        service_match = re.search(r'^(\w+)\[\d+\]:\s*((?:WAR|INF|ERR)\s*-?\s*)?(.+)', message)
        if service_match:
            service, msg_type, content = service_match.groups()
            msg_type = msg_type.strip(' -:') if msg_type else 'INFO'
            
            # Remove variable parts from content
            content = re.sub(r'\[\d+\]', '[PID]', content)
            content = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', 'IP', content)
            
            return f"{service} {msg_type}: {content}"
        
        return message
    
    def get_recent_logs(self, limit: int = 100) -> List[Dict]:
        """Get the most recent processed logs"""
        return list(self.log_buffer)[-limit:]
    
    def clear_old_data(self):
        """Clear old data to prevent memory growth"""
        current_time = datetime.now()
        old_patterns = []
        
        for key, group in self.message_patterns.items():
            try:
                time_diff = current_time - group['parsed_time']
                if time_diff.total_seconds() > 3600:  # Remove patterns older than 1 hour
                    old_patterns.append(key)
            except (KeyError, TypeError):
                continue
                
        for key in old_patterns:
            del self.message_patterns[key]
        
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