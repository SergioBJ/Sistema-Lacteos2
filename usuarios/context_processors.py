import os

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from .menu import ROLES


def menu(request):
    """Pone en todas las plantillas el menú del rol de quien entró."""
    usuario = getattr(request, "user", None)
    if not usuario or not usuario.is_authenticated:
        return {}

    rol = ROLES.get(usuario.rol)
    if rol is None:
        return {"menu_rol": {"nombre": "Sin rol", "color": "#5B6662", "pie": ""}, "menu_items": []}

    actual = request.resolver_match.url_name if request.resolver_match else None
    items = []
    for texto, nombre_ruta in rol["items"]:
        if texto.startswith("§"):
            items.append({"seccion": texto[1:]})
            continue
        try:
            url = reverse(nombre_ruta)
        except NoReverseMatch:
            url = None  # pantalla todavía no construida
        items.append({"texto": texto, "url": url, "activo": bool(actual) and (actual == nombre_ruta or actual.startswith(nombre_ruta + "_"))})
    return {"menu_rol": rol, "menu_items": items}


def version_estilos(request):
    """Número que cambia cada vez que se modifica estilos.css.

    Se agrega al enlace del CSS (estilos.css?v=...) para que el navegador
    no siga usando una copia vieja guardada en caché.
    """
    try:
        return {"version_css": int(os.path.getmtime(settings.BASE_DIR / "static" / "css" / "estilos.css"))}
    except OSError:
        return {"version_css": 1}
