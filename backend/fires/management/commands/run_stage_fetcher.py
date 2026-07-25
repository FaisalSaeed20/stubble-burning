# fires/management/commands/run_stage_fetcher.py

from django.core.management.base import BaseCommand
from fires.stage_fetcher import fetch_and_process_latest_stage_map
import time

class Command(BaseCommand):
    help = 'Manually triggers the GEE stage map fetching and tiling process.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS("🚀 Starting manual stage map fetcher..."))
        self.stdout.write(self.style.WARNING("This process is long-running and may take over 15-20 minutes."))
        
        start_time = time.time()
        
        try:
            fetch_and_process_latest_stage_map()
            end_time = time.time()
            duration = end_time - start_time
            self.stdout.write(self.style.SUCCESS(f"✅ Successfully completed the stage map process in {duration:.2f} seconds."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"❌ An error occurred during the process: {e}"))