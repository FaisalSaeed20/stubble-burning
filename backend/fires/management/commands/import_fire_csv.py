# from django.core.management.base import BaseCommand
# from django.db import transaction
# from fires.models import FirePoint, FireObservation
# import pandas as pd

# class Command(BaseCommand):
#     help = "Import long-format fire CSV into Postgres"

#     def add_arguments(self, parser):
#         parser.add_argument("csv_path", type=str)
#         parser.add_argument("--chunksize", type=int, default=50000)

#     def handle(self, *args, **opts):
#         path = opts["csv_path"]; chunksize = opts["chunksize"]
#         total = 0
#         for chunk in pd.read_csv(path, chunksize=chunksize):
#             for c in ["NDVI","NDWI","NBR","NDRE","VV","VH"]:
#                 if c in chunk.columns:
#                     chunk[c] = pd.to_numeric(chunk[c], errors="coerce")
#             chunk["image_date"] = pd.to_datetime(chunk["image_date"], errors="coerce")
#             chunk["fire_date"]  = pd.to_datetime(chunk["fire_date"], errors="coerce")
#             chunk = chunk.dropna(subset=["point_id","longitude","latitude","image_date"])

#             # Upsert FirePoint by point_id
#             pids = chunk["point_id"].unique().tolist()
#             existing = {p.point_id: p.id for p in FirePoint.objects.filter(point_id__in=pids).only("id","point_id")}
#             to_create = []
#             for pid in pids:
#                 if pid not in existing:
#                     first = chunk[chunk["point_id"] == pid].iloc[0]
#                     to_create.append(FirePoint(
#                         point_id=pid,
#                         fire_date=first["fire_date"],
#                         longitude=float(first["longitude"]),
#                         latitude=float(first["latitude"]),
#                     ))
#             if to_create:
#                 FirePoint.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=5000)
#                 existing.update({p.point_id: p.id for p in FirePoint.objects.filter(point_id__in=pids).only("id","point_id")})

#             # Observations
#             to_obs = []
#             for _, r in chunk.iterrows():
#                 pid = existing.get(r["point_id"])
#                 if not pid: continue
#                 to_obs.append(FireObservation(
#                     point_id=pid,
#                     image_date=r["image_date"],
#                     NDVI=r.get("NDVI"),
#                     NDWI=r.get("NDWI"),
#                     NBR =r.get("NBR"),
#                     NDRE=r.get("NDRE"),
#                     VV  =r.get("VV"),
#                     VH  =r.get("VH"),
#                 ))
#             with transaction.atomic():
#                 FireObservation.objects.bulk_create(to_obs, ignore_conflicts=True, batch_size=5000)
#             total += len(to_obs)
#             self.stdout.write(f"Inserted {len(to_obs)} (total {total})")
#         self.stdout.write(self.style.SUCCESS(f"Done. Total observations: {total}"))
