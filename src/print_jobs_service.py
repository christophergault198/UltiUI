import requests
from datetime import datetime
from typing import List, Dict, Any, Optional

class PrintJobsService:
    def __init__(self, base_url: str = "http://192.168.6.218"):
        self.base_url = base_url
        self.print_jobs_endpoint = f"{base_url}/api/v1/history/print_jobs"

    def get_print_jobs(self, count: Optional[int] = None) -> List[Dict[Any, Any]]:
        """
        Fetch print jobs history from the API endpoint
        Args:
            count: Optional number of print jobs to retrieve
        Returns a list of print job dictionaries
        """
        try:
            url = self.print_jobs_endpoint
            if count is not None:
                url = f"{url}?count={count}"
                
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching print jobs: {e}")
            return []

    def format_job_time(self, time_str: Optional[str]) -> str:
        """
        Format the print job time string to a more readable format
        """
        if not time_str:
            return "N/A"
            
        try:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return time_str

    def format_duration(self, seconds: Optional[float]) -> str:
        """
        Format duration in seconds to a human-readable format
        """
        if seconds is None or seconds <= 0:
            return "N/A"
            
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def get_formatted_print_jobs(self, count: Optional[int] = None) -> List[Dict[Any, Any]]:
        """
        Get print jobs with formatted timestamps and additional fields
        Args:
            count: Optional number of print jobs to retrieve
        """
        print_jobs = self.get_print_jobs(count)
        formatted_jobs = []
        
        for job in print_jobs:
            # Create a new job dictionary with the fields we need
            formatted_job = {
                'id': job.get('uuid', 'N/A'),
                'name': job.get('name', 'N/A'),
                'status': job.get('result', 'Unknown'),  # Map 'result' to 'status'
                'start_time': self.format_job_time(job.get('datetime_started')),
                'end_time': self.format_job_time(job.get('datetime_finished')),
                'duration': self.format_duration(job.get('time_elapsed')),
                'size': f"{job.get('material_0_amount', 0)}mm" if job.get('material_0_amount') else "N/A",
                'layer_height': job.get('printcore_0_name', 'N/A'),
                'material': job.get('material_0_guid', 'N/A')
            }
            formatted_jobs.append(formatted_job)
            
        return formatted_jobs 