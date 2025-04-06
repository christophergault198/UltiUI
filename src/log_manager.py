from datetime import datetime
import re
from typing import Dict, List, Set, Optional
import asyncio
from collections import deque

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
            
            # Determine message type and core content
            message_type = 'info'
            core_message = message
            
            # Handle different message types
            if 'WAR' in message:
                warning_match = re.match(r"PrinterService\[\d+\]:WAR - ([^:]+)", message)
                if warning_match:
                    message_type = 'warning'
                    core_message = f"WAR - {warning_match.group(1)}"
            elif 'Build Complete' in message:
                message_type = 'info'
                core_message = 'Build Complete'
            elif 'ERROR' in message.upper():
                message_type = 'error'
                core_message = message
            elif message.startswith('Okuda'):
                message_type = 'warning'
                # Extract core message without timestamp for Okuda messages
                core_message = re.sub(r'\[\d+\]:', ':', message)
            
            # Create message pattern and get details
            pattern = self.get_message_pattern(message)
            details = self.get_message_details(message, pattern)
            
            # Create unique pattern key that includes more context
            pattern_key = f"{pattern}:{timestamp}"  # Use full timestamp for more granular grouping
            
            # Update pattern tracking
            if pattern_key in self.message_patterns:
                self.message_patterns[pattern_key]['count'] += 1
                self.message_patterns[pattern_key]['last_timestamp'] = timestamp
                if details and details not in self.message_patterns[pattern_key]['details']:
                    self.message_patterns[pattern_key]['details'].append(details)
            else:
                self.message_patterns[pattern_key] = {
                    'count': 1,
                    'last_timestamp': timestamp,
                    'details': [details] if details else [],
                    'type': message_type
                }
            
            # Create log entry
            log_entry = {
                'timestamp': timestamp,
                'message': message,
                'raw': log_entry,
                'type': message_type,
                'pattern': pattern,
                'pattern_key': pattern_key,
                'occurrences': self.message_patterns[pattern_key]['count'],
                'details': self.message_patterns[pattern_key]['details'] if details else None
            }
            
            # Add to buffer if it's a new message
            self.log_buffer.append(log_entry)
            return log_entry
    
    async def process_logs(self, logs: List[str]) -> List[Dict]:
        """Process multiple log entries and return structured data"""
        processed_logs = []
        for log_entry in logs:
            result = await self.process_log_entry(log_entry)
            if result:
                processed_logs.append(result)
        return processed_logs
    
    def get_message_pattern(self, message: str) -> str:
        """Extract a pattern from a message for grouping similar messages"""
        # Special cases for different message types
        if 'MJPG-streamer' in message and 'serving client' in message:
            client_match = re.search(r"serving client: ([^\s]+)", message)
            if client_match:
                return f'MJPG-streamer serving client: {client_match.group(1)}'
            return 'MJPG-streamer serving client'
            
        if 'PrintCore' in message and 'extruded' in message:
            core_match = re.search(r"PrintCore (\d+)", message)
            if core_match:
                return f'PrintCore {core_match.group(1)} extrusion update'
            return 'PrintCore extrusion update'
            
        if 'Queueing tag for hotend' in message:
            hotend_match = re.search(r"hotend (\d+)", message)
            if hotend_match:
                return f'NFC tag queue update for hotend {hotend_match.group(1)}'
            return 'NFC tag queue update'
            
        if 'Writing tag' in message:
            hotend_match = re.search(r"hotend index # (\d+)", message)
            if hotend_match:
                return f'NFC tag write for hotend {hotend_match.group(1)}'
            return 'NFC tag write'
            
        # For other messages, keep more of the original content
        # but remove highly variable parts
        
        # Extract and remove process IDs
        message = re.sub(r'\[\d+\]', '[PID]', message)
        
        # Extract and remove timestamps
        message = re.sub(r'\d{2}:\d{2}:\d{2}', 'TIME', message)
        
        # Extract and remove IP addresses
        message = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', 'IP', message)
        
        # Extract and remove UUIDs
        message = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', 'UUID', message)
        
        return message
    
    def get_message_details(self, message: str, pattern: str) -> Optional[str]:
        """Extract relevant details from a message based on its pattern"""
        if pattern == 'MJPG-streamer serving client':
            client_match = re.search(r"serving client: ([^\s]+)", message)
            return client_match.group(1) if client_match else None
        elif pattern == 'PrintCore extrusion update':
            match = re.search(r"PrintCore (\d+) extruded ([\d.]+) mm in ([\d.]+) s, remaining length = (\d+) mm", message)
            if match:
                return f"Core {match.group(1)}: {match.group(2)}mm in {match.group(3)}s ({match.group(4)}mm remaining)"
        return None
    
    def get_recent_logs(self, limit: int = 100) -> List[Dict]:
        """Get the most recent processed logs"""
        return list(self.log_buffer)[-limit:]
    
    def clear_old_data(self):
        """Clear old data to prevent memory growth"""
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