from django.urls import path

from . import views

urlpatterns = [
    path("almacen/", views.tareas, name="almacen_tareas"),
    path("almacen/recepcion/", views.recepcion, name="almacen_recepcion"),
    path("almacen/entregas/", views.entregas, name="almacen_entrega"),
    path("almacen/entregas/<int:pk>/", views.entrega_orden, name="almacen_entrega_orden"),
    path("almacen/despacho/", views.despachos, name="almacen_despacho"),
    path("almacen/despacho/<int:pk>/", views.despacho_lote, name="almacen_despacho_lote"),
]
