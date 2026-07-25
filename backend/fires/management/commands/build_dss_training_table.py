import datetime

import ee
from django.conf import settings
from django.core.management.base import BaseCommand

from fires.gee_assets.build_dss_training_table import build_dss_training_table, export_dss_training_table
from fires.gee_assets.common import init_ee


class Command(BaseCommand):
    help = 'Builds (and optionally exports) the DSS training table for the growth-stage classifier.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=datetime.datetime.now().year)
        parser.add_argument('--dry-run', action='store_true', help='Compute stats only, do not export.')
        parser.add_argument('--asset-id', type=str, default=None, help='Override settings.GEE_DSS_TRAINING_TABLE_ASSET_ID.')
        parser.add_argument('--force', action='store_true', help='Delete the target asset first if it already exists.')

    def handle(self, *args, **options):
        init_ee()
        table = build_dss_training_table(options['year'])

        row_count = table.size().getInfo()
        dss_stats = table.aggregate_min('DSS').getInfo(), table.aggregate_mean('DSS').getInfo(), table.aggregate_max('DSS').getInfo()
        self.stdout.write(f'Training rows: {row_count}')
        self.stdout.write(f'DSS min/mean/max: {dss_stats[0]:.1f} / {dss_stats[1]:.1f} / {dss_stats[2]:.1f}')

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS('Dry run complete, nothing exported.'))
            return

        asset_id = options['asset_id'] or settings.GEE_DSS_TRAINING_TABLE_ASSET_ID
        if not asset_id:
            raise ValueError('No asset id: pass --asset-id or set GEE_DSS_TRAINING_TABLE_ASSET_ID.')

        if options['force']:
            try:
                ee.data.deleteAsset(asset_id)
                self.stdout.write(f'Deleted existing asset {asset_id}.')
            except ee.EEException:
                pass

        export_dss_training_table(table, asset_id)
        self.stdout.write(self.style.SUCCESS(f'DSS training table exported to {asset_id}.'))
