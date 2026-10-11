from django.urls import path

from . import descargas, views

urlpatterns = [
    path("gerente/", views.resumen, name="gerente_resumen"),
    path("gerente/graficas/", views.graficas, name="gerente_graficas"),
    path("gerente/historial/", views.historial, name="gerente_historial"),
    path("gerente/trazabilidad/", views.trazabilidad, name="gerente_trazabilidad"),
    path("gerente/reportes/<slug:nombre>/<str:formato>/", descargas.descargar, name="gerente_reporte"),
]
