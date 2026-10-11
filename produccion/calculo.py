"""Cuántos materiales necesita una orden y si alcanzan."""
from collections import defaultdict
from decimal import Decimal

from catalogo.models import Material
from inventario.stock import stock_materiales

from .models import FormulaEmpaque, FormulaLimpieza, FormulaMateria, OrdenProduccion


def necesidades(tamano, cantidad):
    """{material: cantidad necesaria} para producir `cantidad` unidades de `tamano`."""
    total = defaultdict(Decimal)
    kg_totales = tamano.peso_kg * Decimal(cantidad)
    for f in FormulaMateria.objects.filter(producto=tamano.producto).select_related("material"):
        total[f.material] += kg_totales * f.cantidad_por_kg
    for f in FormulaEmpaque.objects.filter(tamano=tamano).select_related("material"):
        total[f.material] += Decimal(cantidad) * f.cantidad_por_unidad
    for f in FormulaLimpieza.objects.filter(producto=tamano.producto).select_related("material"):
        total[f.material] += f.cantidad_por_orden
    return dict(total)


def faltantes_de_formula(tamano):
    """Lista de problemas de la fórmula que impiden calcular la orden."""
    problemas = []
    if not FormulaMateria.objects.filter(producto=tamano.producto).exists():
        problemas.append(f"{tamano.producto} no tiene materia prima en su fórmula.")
    if not FormulaEmpaque.objects.filter(tamano=tamano).exists():
        problemas.append(f"El tamaño {tamano.empaque} {tamano.cantidad:g} {tamano.unidad} no tiene empaque en la fórmula.")
    return problemas


def reservado(excluir_orden=None):
    """Material comprometido en órdenes que esperan sus materiales (aún no entregados)."""
    total = defaultdict(Decimal)
    ordenes = OrdenProduccion.objects.filter(estado=OrdenProduccion.Estado.ESPERANDO_MATERIALES).select_related("tamano__producto")
    if excluir_orden is not None:
        ordenes = ordenes.exclude(pk=excluir_orden.pk)
    for o in ordenes:
        for material, cant in necesidades(o.tamano, o.cantidad).items():
            total[material.pk] += cant
    return total


def revisar_disponibilidad(tamano, cantidad, excluir_orden=None):
    """Filas para la tabla: material, necesita, disponible, alcanza."""
    stock = stock_materiales()
    comprometido = reservado(excluir_orden)
    filas = []
    for material, cant in sorted(necesidades(tamano, cantidad).items(), key=lambda x: (x[0].tipo, x[0].nombre)):
        disponible = stock.get(material.pk, Decimal("0")) - comprometido.get(material.pk, Decimal("0"))
        filas.append({
            "material": material,
            "necesita": cant.quantize(Decimal("0.01")),
            "disponible": max(disponible, Decimal("0")).quantize(Decimal("0.01")),
            "alcanza": disponible >= cant,
        })
    return filas


def texto_faltantes(filas):
    return "; ".join(
        f"Falta {f['material'].nombre} (hay {f['disponible']:g} de {f['necesita']:g} {f['material'].unidad})"
        for f in filas if not f["alcanza"]
    )
