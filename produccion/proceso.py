"""Parámetros del proceso que registra el Operador.

PENDIENTE (punto 1 de la revisión del bosquejo): definir quién fija estos rangos.
Mientras se decide, quedan aquí como valores de referencia y se pueden cambiar en este archivo.
"""
from decimal import Decimal

PARAMETROS_PROCESO = [
    # (nombre, mínimo, máximo, unidad)
    ("Temperatura de pasteurización", Decimal("72"), Decimal("76"), "°C"),
    ("Tiempo de pasteurización", Decimal("15"), Decimal("20"), "s"),
    ("Temperatura de secado", Decimal("160"), Decimal("200"), "°C"),
]
