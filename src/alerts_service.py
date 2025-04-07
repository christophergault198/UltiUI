from datetime import datetime
from typing import Dict, List, Optional
import asyncio
from collections import deque
import hashlib
import re

class AlertsService:
    def __init__(self):
        self.active_alerts = {}  # Store active alerts by ID
        self.alert_history = deque(maxlen=1000)  # Store alert history
        self.lock = asyncio.Lock()  # Thread safety for alert processing
        self.local_alerts = {}  # Store local UI alerts (like system connection status)
        
    def _normalize_message(self, message: str) -> str:
        """Normalize a message by removing variable parts like timestamps and IDs"""
        # Special handling for build completion alerts
        if "Build has completed and is waiting for cleanup" in message:
            return "Build has completed and is waiting for cleanup"
        
        # Special handling for system update alerts
        if "Next update check scheduled for" in message:
            return "Next update check scheduled"
        
        # Special handling for Stardust connection issues
        if "Stardust service connection issues" in message:
            return "Stardust service connection issues"
        
        # Remove timestamps
        message = re.sub(r'\b\d{2}:\d{2}:\d{2}\b', 'TIME', message)
        # Remove specific dates
        message = re.sub(r'\b[A-Z][a-z]{2} \d{2}\b', 'DATE', message)
        # Remove numbers but keep percentages
        message = re.sub(r'(?<!\d)(\d+(\.\d+)?(?!\%))', 'NUM', message)
        # Remove UUIDs and hex values
        message = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID', message)
        message = re.sub(r'0x[0-9a-f]+', 'HEX', message)
        return message
        
    def _generate_alert_id(self, alert_data: Dict) -> str:
        """Generate a consistent ID for an alert based on its content"""
        # Create a normalized version of the message
        message = alert_data.get('message', '')
        if 'details' in alert_data and 'raw_message' in alert_data['details']:
            message = alert_data['details']['raw_message']
            
        normalized_message = self._normalize_message(message)
        
        # Create a unique identifier based on the alert's content
        content_str = f"{alert_data.get('type', '')}-{normalized_message}"
        return hashlib.md5(content_str.encode()).hexdigest()
        
    async def process_alert(self, alert_data: Dict) -> Optional[Dict]:
        """Process a new alert and update active alerts"""
        async with self.lock:
            # Generate a consistent ID based on normalized content
            alert_id = self._generate_alert_id(alert_data)
            alert_data['id'] = alert_id
            
            # Don't process alerts that have been resolved recently (within last minute)
            recent_resolved = any(
                alert['id'] == alert_id and alert.get('resolved_at') and
                (datetime.now() - datetime.fromisoformat(alert['resolved_at'])).total_seconds() < 60
                for alert in self.alert_history
            )
            if recent_resolved:
                return None
                
            # Check if this is a new alert or an update to an existing one
            if alert_id in self.active_alerts:
                existing_alert = self.active_alerts[alert_id]
                # Only update if the message has changed or significant time has passed
                time_diff = (datetime.now() - datetime.fromisoformat(existing_alert['updated_at'])).total_seconds()
                if time_diff > 60:  # Update if more than 60 seconds have passed
                    existing_alert['updated_at'] = datetime.now().isoformat()
                    existing_alert['occurrence_count'] = existing_alert.get('occurrence_count', 1) + 1
                    if 'details' in alert_data:
                        existing_alert['details'] = alert_data['details']
                return existing_alert
            else:
                # Add new alert
                alert_data['created_at'] = datetime.now().isoformat()
                alert_data['updated_at'] = alert_data['created_at']
                alert_data['occurrence_count'] = 1
                self.active_alerts[alert_id] = alert_data
                
                # Add to history
                self.alert_history.append({
                    'id': alert_id,
                    'type': alert_data.get('type', 'info'),
                    'message': alert_data.get('message', ''),
                    'created_at': alert_data.get('created_at'),
                    'updated_at': alert_data.get('updated_at'),
                    'details': alert_data.get('details', {}),
                    'occurrence_count': 1
                })
                
                return alert_data
            
    async def resolve_alert(self, alert_id: str) -> Optional[Dict]:
        """Mark an alert as resolved"""
        async with self.lock:
            if alert_id not in self.active_alerts:
                return None
                
            alert = self.active_alerts[alert_id]
            alert['resolved_at'] = datetime.now().isoformat()
            
            # Add resolution to history
            self.alert_history.append({
                'id': alert_id,
                'type': alert.get('type', 'info'),
                'message': alert.get('message', ''),
                'created_at': alert.get('created_at'),
                'updated_at': alert.get('updated_at'),
                'resolved_at': alert.get('resolved_at'),
                'details': alert.get('details', {}),
                'occurrence_count': alert.get('occurrence_count', 1),
                'resolved': True
            })
            
            # Remove from active alerts
            del self.active_alerts[alert_id]
            
            return alert
            
    def get_active_alerts(self) -> List[Dict]:
        """Get all active alerts"""
        # Combine server alerts and local UI alerts
        alerts = list(self.active_alerts.values())
        alerts.extend(self.local_alerts.values())
        return alerts
        
    def get_alert_history(self, limit: int = 100) -> List[Dict]:
        """Get alert history"""
        return list(self.alert_history)[-limit:]
        
    async def clear_old_alerts(self, max_age_hours: int = 24):
        """Clear alerts older than max_age_hours"""
        current_time = datetime.now()
        async with self.lock:
            # Clear old active alerts based on last update time
            self.active_alerts = {
                k: v for k, v in self.active_alerts.items()
                if (current_time - datetime.fromisoformat(v['updated_at'])).total_seconds() < max_age_hours * 3600
            }
            
            # Clear old history
            self.alert_history = deque(
                (alert for alert in self.alert_history
                 if (current_time - datetime.fromisoformat(alert['created_at'])).total_seconds() < max_age_hours * 3600),
                maxlen=1000
            )
            
            # Clear old local alerts
            self.local_alerts = {
                k: v for k, v in self.local_alerts.items()
                if (current_time - datetime.fromisoformat(v['created_at'])).total_seconds() < max_age_hours * 3600
            } 