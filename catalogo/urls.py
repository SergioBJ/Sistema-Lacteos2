from django.urls import path

from . import views

urlpatterns = [
    path("gerente/proveedores/", views.proveedores, name="gerente_proveedores"),
    path("gerente/proveedores/<int:pk>/", views.proveedores, name="gerente_proveedores_editar"),
    path("gerente/proveedores/<int:pk>/estado/", views.proveedor_estado, name="gerente_proveedores_estado"),

    path("gerente/clientes/", views.clientes, name="gerente_clientes"),
    path("gerente/clientes/<int:pk>/", views.clientes, name="gerente_clientes_editar"),
    path("gerente/clientes/<int:pk>/estado/", views.cliente_estado, name="gerente_clientes_estado"),

    path("gerente/materiales/", views.materiales, name="gerente_materiales"),
    path("gerente/materiales/<int:pk>/", views.materiales, name="gerente_materiales_editar"),
    path("gerente/materiales/<int:pk>/estado/", views.material_estado, name="gerente_materiales_estado"),

    path("gerente/productos/", views.productos, name="gerente_materiales_productos"),
    path("gerente/productos/<int:pk>/", views.productos, name="gerente_materiales_productos_editar"),
    path("gerente/productos/<int:pk>/estado/", views.producto_estado, name="gerente_materiales_productos_estado"),
]
