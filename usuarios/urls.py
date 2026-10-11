from django.urls import path

from . import views

urlpatterns = [
    path("gerente/usuarios/", views.usuarios, name="gerente_usuarios"),
    path("gerente/usuarios/<int:pk>/", views.usuarios, name="gerente_usuarios_editar"),
    path("gerente/usuarios/<int:pk>/estado/", views.usuario_estado, name="gerente_usuarios_estado"),
]
