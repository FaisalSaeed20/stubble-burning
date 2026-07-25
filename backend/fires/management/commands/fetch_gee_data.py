# fires/management/commands/fetch_gee_data.py

from django.core.management.base import BaseCommand
from fires.gee_fetcher import fetch_and_load_new_fires

class Command(BaseCommand):
    help = 'Fetches the latest fire data from Google Earth Engine and loads it into the database.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting GEE data fetch...'))

        try:
            fetch_and_load_new_fires()
            self.stdout.write(self.style.SUCCESS('Successfully completed GEE data fetch.'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'An error occurred: {e}'))