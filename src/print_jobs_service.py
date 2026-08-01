from datetime import datetime
from typing import Optional

from services.base_api import PrinterApiService


class PrintJobsService(PrinterApiService):
    def __init__(self, base_url: str = "", api_key: str = None,
                 auth_username: str = None, auth_password: str = None):
        super().__init__(base_url, api_key, auth_username, auth_password)
        self.print_jobs_endpoint = "/api/v1/history/print_jobs"

    async def get_print_jobs(self, count: Optional[int] = None) -> list:
        return await self._fetch(self.print_jobs_endpoint, count)

    def format_job_time(self, time_str: Optional[str]) -> str:
        if not time_str:
            return "N/A"
        try:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return time_str or "N/A"

    def format_duration(self, seconds: Optional[float]) -> str:
        if seconds is None or seconds <= 0:
            return "N/A"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    async def get_formatted_print_jobs(self, count: Optional[int] = None) -> list:
        print_jobs = await self.get_print_jobs(count)
        formatted_jobs = []
        for job in print_jobs:
            formatted_job = {
                'id': job.get('uuid', 'N/A'),
                'name': job.get('name', 'N/A'),
                'status': job.get('result', 'Unknown'),
                'start_time': self.format_job_time(job.get('datetime_started')),
                'end_time': self.format_job_time(job.get('datetime_finished')),
                'duration': self.format_duration(job.get('time_elapsed')),
                'size': f"{job.get('material_0_amount', 0)}mm" if job.get('material_0_amount') else "N/A",
                'layer_height': job.get('printcore_0_name', 'N/A'),
                'material': job.get('material_0_guid', 'N/A')
            }
            formatted_jobs.append(formatted_job)
        return formatted_jobs
