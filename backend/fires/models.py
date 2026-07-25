from django.db import models

class FirePoint(models.Model):
    point_id = models.CharField(max_length=100, unique=True)
    fire_date = models.DateTimeField(null=True, blank=True)
    longitude = models.FloatField()
    latitude = models.FloatField()
    province = models.CharField(max_length=80, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["point_id"]),
            models.Index(fields=["longitude", "latitude"]),
        ]

class FireObservation(models.Model):
    point = models.ForeignKey(FirePoint, on_delete=models.CASCADE, related_name="obs")
    image_date = models.DateTimeField()

    NDVI = models.FloatField(null=True, blank=True)
    NDWI = models.FloatField(null=True, blank=True)
    NBR  = models.FloatField(null=True, blank=True)
    NDRE = models.FloatField(null=True, blank=True)
    VV   = models.FloatField(null=True, blank=True)
    VH   = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("point", "image_date")
        indexes = [models.Index(fields=["image_date"])]


class StageTileDate(models.Model):
    """Marks a growth-stage tile pyramid (YYYYMMDD) as fully generated in GCS.

    Doubles as the pipeline's idempotency guard (replacing a local
    os.path.exists check, which doesn't survive across Cloud Run instances)
    and as the data source for the stage-dates list endpoint.
    """
    date_str = models.CharField(max_length=8, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date_str"]
