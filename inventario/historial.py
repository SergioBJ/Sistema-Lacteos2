"""Una sola función para escribir en el historial. Todas las pantallas la usan."""
from .models import Movimiento


def registrar(usuario, etapa, accion, paso, referencia, motivo=""):
    if not paso and not motivo.strip():
        raise ValueError("Si no pasó, el motivo es obligatorio")
    return Movimiento.objects.create(
        usuario=usuario,
        etapa=etapa,
        accion=accion,
        paso=paso,
        referencia=referencia,
        motivo=motivo,
    )
