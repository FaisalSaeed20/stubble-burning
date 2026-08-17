# from django.urls import path
# from . import views

# urlpatterns = [
#     path('tiles/<int:z>/<int:x>/<int:y>.png', views.serve_tile, name='serve_tile'),
#     path('fire-data/', views.get_fire_data, name='get_fire_data'),
# ]
from django.urls import path
from . import views
import re
urlpatterns = [
    path('healthz/', views.healthz, name='healthz'),
    path('tiles/<int:z>/<int:x>/<int:y>.png', views.serve_tile, name='serve_tile'),
    path('fire-timeseries/', views.get_fire_timeseries, name='get_fire_timeseries'),
    path('api/districts/', views.get_districts, name='get_districts'),
    path('dashboard-summary/', views.get_dashboard_summary, name='get_dashboard_summary'),
    path('district-summary/', views.get_district_summary, name='get_district_summary'),
    path('incidents/', views.get_incidents, name='get_incidents'),
        # --- NEW URLS ---
    path('heatmap-tiles/<str:gas_type>/<int:z>/<int:x>/<int:y>.png', views.serve_heatmap_tile, name='serve_heatmap_tile'),
    path('stage-tiles/<int:date>/<int:z>/<int:x>/<int:y>.png', views.serve_stage_tile, name='serve_stage_tile'),
    
    # This provides the date list for the frontend sliders
    path('stage-dates/', views.get_stage_dates, name='get_stage_dates'),

     path('fire-report/<str:point_id>/', views.fire_report, name='fire_report'),

    # --- Cloud Scheduler trigger endpoints (shared-secret auth, see settings.CLOUD_SCHEDULER_TOKEN) ---
    path('trigger-fetch/', views.trigger_fetch, name='trigger_fetch'),
    path('trigger-stage-fetch/', views.trigger_stage_fetch, name='trigger_stage_fetch'),
]