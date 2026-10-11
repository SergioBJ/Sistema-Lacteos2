from django.urls import path

from . import views

urlpatterns = [
    path("calidad/", views.tareas, name="calidad_tareas"),
    path("calidad/revision/", views.revision_lista, name="calidad_revision"),
    path("calidad/revision/<int:pk>/", views.revision, name="calidad_revision_detalle"),
    path("calidad/liberacion/", views.liberacion_lista, name="calidad_liberacion"),
    path("calidad/liberacion/<int:pk>/", views.liberacion, name="calidad_liberacion_lote"),
    path("calidad/parametros/", views.parametros, name="calidad_parametros"),
    path("calidad/parametros/<int:pk>/estado/", views.parametro_estado, name="calidad_parametros_estado"),
]
