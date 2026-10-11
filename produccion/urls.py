from django.urls import path

from . import views

urlpatterns = [
    path("jefe/", views.ordenes, name="jefe_ordenes"),
    path("jefe/ordenes/<int:pk>/reintentar/", views.orden_reintentar, name="jefe_ordenes_reintentar"),
    path("jefe/nueva/", views.nueva_orden, name="jefe_nueva"),
    path("jefe/formulas/", views.formulas, name="jefe_formulas"),
    path("jefe/formulas/<str:seccion>/<int:pk>/quitar/", views.formula_quitar, name="jefe_formulas_quitar"),
    path("jefe/revisar/", views.revisar_lista, name="jefe_revisar"),
    path("jefe/revisar/<int:pk>/", views.revisar, name="jefe_revisar_orden"),
    path("operador/", views.operador_orden, name="operador_orden"),
    path("operador/registro/", views.operador_registro, name="operador_registro"),
]
