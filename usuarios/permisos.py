from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def rol_requerido(*roles):
    """Deja entrar a una pantalla solo a los roles indicados.

    - Si no ha iniciado sesión, lo manda al inicio de sesión.
    - Si tiene otro rol, muestra la página "No tienes permiso" (403).

    Uso:
        @rol_requerido("ALMACENISTA")
        def registrar_llegada(request):
            ...
    """
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.rol not in roles:
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador
