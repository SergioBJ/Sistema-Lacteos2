"""Cálculo del inventario de materiales.

Inventario de un material = lo aprobado por Calidad − lo entregado a producción.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from .models import EntregaDetalle, Llegada


def stock_materiales():
    """Devuelve {material_id: cantidad disponible en bodega}."""
    stock = defaultdict(Decimal)
    for fila in (Llegada.objects.filter(estado=Llegada.Estado.APROBADA)
                 .values("material_id").annotate(total=Sum("cantidad"))):
        stock[fila["material_id"]] += fila["total"] or Decimal("0")
    for fila in EntregaDetalle.objects.values("llegada__material_id").annotate(total=Sum("cantidad")):
        stock[fila["llegada__material_id"]] -= fila["total"] or Decimal("0")
    return stock


def lotes_disponibles(material):
    """Lotes aprobados de un material que aún tienen saldo y no están vencidos.

    Ordenados por vencimiento: primero sale lo que vence primero (FEFO).
    """
    from django.utils import timezone

    entregado = {
        f["llegada_id"]: f["total"]
        for f in EntregaDetalle.objects.filter(llegada__material=material)
        .values("llegada_id").annotate(total=Sum("cantidad"))
    }
    lotes = []
    for llegada in (Llegada.objects.filter(material=material, estado=Llegada.Estado.APROBADA,
                                           vencimiento__gte=timezone.localdate())
                    .select_related("proveedor").order_by("vencimiento", "fecha")):
        saldo = llegada.cantidad - entregado.get(llegada.pk, Decimal("0"))
        if saldo > 0:
            lotes.append((llegada, saldo))
    return lotes


def repartir_en_lotes(material, necesita):
    """Decide de qué lotes sacar `necesita`. Devuelve (lista de (llegada, cantidad), faltante)."""
    plan, pendiente = [], necesita
    for llegada, saldo in lotes_disponibles(material):
        if pendiente <= 0:
            break
        toma = min(saldo, pendiente)
        plan.append((llegada, toma))
        pendiente -= toma
    return plan, max(pendiente, Decimal("0"))
