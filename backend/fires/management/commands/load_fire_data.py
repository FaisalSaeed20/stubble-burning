# fires/management/commands/load_fire_data.py

import csv
from django.core.management.base import BaseCommand
from fires.models import FirePoint, FireObservation
from django.utils.dateparse import parse_datetime
from django.db import transaction
from datetime import timezone
from collections import defaultdict

class Command(BaseCommand):
    help = 'Correctly loads and merges S1/S2 fire data from a CSV file.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file_path', type=str, help='The full path to the CSV file')

    @transaction.atomic
    def handle(self, *args, **options):
        # 1. Clear existing data for a clean import
        self.stdout.write("Clearing existing fire data before import...")
        FirePoint.objects.all().delete()

        file_path = options['csv_file_path']
        self.stdout.write(f"Starting import from {file_path}...")

        # 2. Read all rows and group them by point_id and image_date to merge S1/S2 data
        consolidated_observations = {}
        all_points_data = {}
        
        S1_BANDS = ['VV', 'VH']
        S2_BANDS = ['NDVI', 'NDWI', 'NBR', 'NDRE']
        ALL_METRICS = S1_BANDS + S2_BANDS

        with open(file_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                point_id = row['point_id']
                image_date_str = row['image_date']
                
                # Store the point metadata once
                if point_id not in all_points_data:
                    all_points_data[point_id] = {
                        'fire_date': row['fire_date'],
                        'longitude': row['longitude'],
                        'latitude': row['latitude']
                    }

                # Group observations by point and date
                key = (point_id, image_date_str)
                if key not in consolidated_observations:
                    consolidated_observations[key] = {metric: None for metric in ALL_METRICS}
                
                # Populate metrics from the current row, merging S1 and S2 values
                for metric in ALL_METRICS:
                    if row.get(metric) and row[metric] != '':
                        consolidated_observations[key][metric] = float(row[metric])

        self.stdout.write(f"Consolidated data into {len(consolidated_observations)} unique observations.")

        # 3. Bulk create all FirePoint objects
        points_to_create = [
            FirePoint(
                point_id=pid,
                fire_date=parse_datetime(pdata['fire_date']).replace(tzinfo=timezone.utc),
                longitude=float(pdata['longitude']),
                latitude=float(pdata['latitude'])
            ) for pid, pdata in all_points_data.items()
        ]

        if points_to_create:
            FirePoint.objects.bulk_create(points_to_create)
            self.stdout.write(f"Bulk created {len(points_to_create)} FirePoints.")

        # 4. Create a map of point_id to FirePoint object for efficient linking
        point_map = {p.point_id: p for p in FirePoint.objects.all()}

        # 5. Bulk create all consolidated FireObservation objects
        observations_to_create = [
            FireObservation(
                point=point_map[key[0]],
                image_date=parse_datetime(key[1]).replace(tzinfo=timezone.utc),
                **metrics
            ) for key, metrics in consolidated_observations.items()
        ]

        if observations_to_create:
            FireObservation.objects.bulk_create(observations_to_create)
            self.stdout.write(f"Bulk created {len(observations_to_create)} merged FireObservations.")

        self.stdout.write(self.style.SUCCESS('Successfully and correctly loaded all fire data.'))