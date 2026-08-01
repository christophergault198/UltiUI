import asyncio
import hashlib
import re
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional

from logger import logger


class AlertsService:
    def __init__(self):
        self.active_alerts: Dict[str, dict] = {}
        self.alert_history: deque = deque(maxlen=1000)
        self.lock = asyncio.Lock()
        self.local_alerts: Dict[str, dict] = {}
        self._last_hash: str | None = None

    def _normalize_message(self, message: str) -> str:
        if "Build has completed and is waiting for cleanup" in message:
            return "Build has completed and is waiting for cleanup"
        if "Next update check scheduled for" in message:
            return "Next update check scheduled"
        if "Stardust service connection issues" in message:
            return "Stardust service connection issues"
        message = re.sub(r'\b\d{2}:\d{2}:\d{2}\b', 'TIME', message)
        message = re.sub(r'\b[A-Z][a-z]{2} \d{2}\b', 'DATE', message)
        message = re.sub(r'(?<!\d)(\d+(\.\d+)?(?!\%))', 'NUM', message)
        message = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 'UUID', message)
        message = re.sub(r'0x[0-9a-f]+', 'HEX', message)
        return message

    def _generate_alert_id(self, alert_data: Dict) -> str:
        message = alert_data.get('message', '')
        if 'details' in alert_data and 'raw_message' in alert_data['details']:
            message = alert_data['details']['raw_message']
        normalized_message = self._normalize_message(message)
        content_str = f"{alert_data.get('type', '')}-{normalized_message}"
        return hashlib.md5(content_str.encode()).hexdigest()

    def _alerts_changed(self) -> bool:
        current = self.get_active_alerts()
        current_hash = hashlib.md5(
            str(sorted([(a.get('id', ''), a.get('updated_at', '')) for a in current])).encode()
        ).hexdigest()
        if current_hash != self._last_hash:
            self._last_hash = current_hash
            return True
        return False

    async def process_alert(self, alert_data: Dict) -> Optional[Dict]:
        async with self.lock:
            alert_id = self._generate_alert_id(alert_data)
            alert_data['id'] = alert_id

            recent_resolved = any(
                alert['id'] == alert_id and alert.get('resolved_at') and
                (datetime.now() - datetime.fromisoformat(alert['resolved_at'])).total_seconds() < 60
                for alert in self.alert_history
            )
            if recent_resolved:
                return None

            if alert_id in self.active_alerts:
                existing_alert = self.active_alerts[alert_id]
                time_diff = (datetime.now() - datetime.fromisoformat(existing_alert['updated_at'])).total_seconds()
                if time_diff > 60:
                    existing_alert['updated_at'] = datetime.now().isoformat()
                    existing_alert['occurrence_count'] = existing_alert.get('occurrence_count', 1) + 1
                    if 'details' in alert_data:
                        existing_alert['details'] = alert_data['details']
                return existing_alert
            else:
                alert_data['created_at'] = datetime.now().isoformat()
                alert_data['updated_at'] = alert_data['created_at']
                alert_data['occurrence_count'] = 1
                self.active_alerts[alert_id] = alert_data

                self.alert_history.append({
                    'id': alert_id,
                    'type': alert_data.get('type', 'info'),
                    'message': alert_data.get('message', ''),
                    'created_at': alert_data.get('created_at'),
                    'updated_at': alert_data.get('updated_at'),
                    'details': alert_data.get('details', {}),
                    'occurrence_count': 1
                })

                logger.debug('New alert: %s [%s]', alert_data.get('message'), alert_data.get('type'))
                return alert_data

    async def resolve_alert(self, alert_id: str) -> Optional[Dict]:
        async with self.lock:
            if alert_id not in self.active_alerts:
                return None
            alert = self.active_alerts[alert_id]
            alert['resolved_at'] = datetime.now().isoformat()

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

            del self.active_alerts[alert_id]
            logger.info('Resolved alert: %s', alert.get('message'))
            return alert

    def get_active_alerts(self) -> List[Dict]:
        alerts = list(self.active_alerts.values())
        alerts.extend(self.local_alerts.values())
        return alerts

    def get_alert_history(self, limit: int = 100) -> List[Dict]:
        return list(self.alert_history)[-limit:]

    async def clear_old_alerts(self, max_age_hours: int = 24):
        current_time = datetime.now()
        async with self.lock:
            self.active_alerts = {
                k: v for k, v in self.active_alerts.items()
                if (current_time - datetime.fromisoformat(v['updated_at'])).total_seconds() < max_age_hours * 3600
            }
            cutoff = max_age_hours * 3600
            self.alert_history = deque(
                (
                    alert for alert in self.alert_history
                    if (current_time - datetime.fromisoformat(alert['created_at'])).total_seconds() < cutoff
                ),
                maxlen=1000
            )
            self.local_alerts = {
                k: v for k, v in self.local_alerts.items()
                if (current_time - datetime.fromisoformat(v['created_at'])).total_seconds() < max_age_hours * 3600
            }
