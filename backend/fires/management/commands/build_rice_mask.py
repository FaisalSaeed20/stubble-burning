import datetime

import ee
from django.conf import settings
from django.core.management.base import BaseCommand

from fires.gee_assets.build_rice_mask import (
    build_rice_mask,
    compute_rice_area_hectares,
    export_rice_mask,
    export_rice_mask_by_district,
)
from fires.gee_assets.common import init_ee
from fires.models import RiceAreaEstimate


class Command(BaseCommand):
    help = 'Builds (and optionally exports) the rice-cropland mask for Punjab.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=datetime.datetime.now().year)
        parser.add_argument('--dry-run', action='store_true', help='Compute stats only, do not export.')
        parser.add_argument('--asset-id', type=str, default=None, help='Override settings.GEE_RICE_MASK_ASSET_ID.')
        parser.add_argument('--force', action='store_true', help='Delete the target asset first if it already exists.')
        parser.add_argument(
            '--by-district', action='store_true',
            help='Export as one asset per district instead of a single province-wide export -- a single '
                 'province-wide export can stall for a very long time on the free-tier batch queue.',
        )

    def handle(self, *args, **options):
        init_ee()
        rice_mask, aoi = build_rice_mask(options['year'])

        hectares = compute_rice_area_hectares(rice_mask, aoi)
        self.stdout.write(f"Candidate rice area for {options['year']}: {hectares:,.1f} ha")
        RiceAreaEstimate.objects.create(hectares=hectares, season_year=options['year'])

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS('Dry run complete, nothing exported.'))
            return

        asset_id = options['asset_id'] or settings.GEE_RICE_MASK_ASSET_ID
        if not asset_id:
            raise ValueError('No asset id: pass --asset-id or set GEE_RICE_MASK_ASSET_ID.')

        if options['by_district']:
            asset_ids = export_rice_mask_by_district(rice_mask, asset_id)
            self.stdout.write(self.style.SUCCESS(
                f'Rice mask exported as {len(asset_ids)} per-district assets under prefix {asset_id}_*.'
            ))
            return

        if options['force']:
            try:
                ee.data.deleteAsset(asset_id)
                self.stdout.write(f'Deleted existing asset {asset_id}.')
            except ee.EEException:
                pass

        export_rice_mask(rice_mask, aoi, asset_id)
        self.stdout.write(self.style.SUCCESS(f'Rice mask exported to {asset_id}.'))
