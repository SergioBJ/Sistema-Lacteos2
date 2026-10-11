from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch
from django.utils.html import format_html

from catalogo.vistas_base import cambiar_estado, lista_y_formulario

from .forms import UsuarioCrearForm, UsuarioEditarForm
from .menu import ROLES
from .models import Usuario
from .permisos import rol_requerido

# Pantalla a la que va cada rol después de iniciar sesión.
DESTINO = {
    "GERENTE": "gerente_resumen",
    "CALIDAD": "calidad_tareas",
    "JEFE": "jefe_ordenes",
    "ALMACENISTA": "almacen_tareas",
    "OPERADOR": "operador_orden",
}


@login_required
def inicio(request):
    try:
        return redirect(DESTINO[request.user.rol])
    except (KeyError, NoReverseMatch):
        # Mientras la pantalla principal del rol no exista, se muestra esta página.
        return render(request, "inicio_provisional.html")


def _pill_rol(u):
    rol = ROLES.get(u.rol, {"nombre": "Sin rol", "color": "#5B6662"})
    return format_html('<span class="pill" style="background: {}1A; color: {}">{}</span>',
                       rol["color"], rol["color"], rol["nombre"])


USUARIOS = {
    "modelo": Usuario,
    "form": UsuarioCrearForm,
    "form_editar": UsuarioEditarForm,
    "ruta": "gerente_usuarios",
    "titulo": "Usuarios",
    "sub": "Crea a cada persona con un solo rol y su correo. Si alguien se va, se desactiva: su historial queda.",
    "que": "el usuario",
    "nuevo": "Nuevo usuario",
    "cabeceras": ["Nombre", "Usuario", "Correo", "Rol"],
    "fila": lambda u: [u.get_full_name() or "—", u.username, u.email, _pill_rol(u)],
    "nombre": lambda u: u.username,
    "referencia": lambda u: u.username,
    "buscar_en": ["username", "first_name", "last_name", "email"],
    "campo_activo": "is_active",
    "puede_desactivar": lambda request, u: u.pk != request.user.pk,
}


@rol_requerido("GERENTE")
def usuarios(request, pk=None):
    return lista_y_formulario(request, USUARIOS, pk)


@rol_requerido("GERENTE")
def usuario_estado(request, pk):
    return cambiar_estado(request, USUARIOS, pk)


# ---------------------------------------------------------------------
# Recuperar contraseña
# ---------------------------------------------------------------------
from django.contrib.auth.views import PasswordResetView  # noqa: E402

from .forms import RecuperarForm  # noqa: E402


class RecuperarView(PasswordResetView):
    form_class = RecuperarForm
    email_template_name = "registration/password_reset_email.txt"
    subject_template_name = "registration/password_reset_subject.txt"
