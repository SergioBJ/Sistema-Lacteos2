"""Los datos de cada reporte, en un formato común que luego se convierte a Excel o PDF.

Cada reporte devuelve un diccionario:
    titulo, subtitulo, filtros (lista de textos), kpis (lista de {valor, texto, cambio}),
    secciones (lista de {titulo, cabeceras, filas, nota}), nota_final
"""
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from catalogo.models import Material, Proveedor, Tamano
from inventario.models import Despacho, EntregaDetalle, Llegada, Movimiento
from inventario.stock import stock_materiales
from produccion.models import OrdenProduccion
from usuarios.menu import ROLES

from .views import _categoria_no_conformidad, inventario_producto_terminado, lotes_por_vencer


def _n(valor, decimales=2):
    """Número con formato colombiano: 12.345,5"""
    if valor is None:
        return "—"
    if isinstance(valor, Decimal):
        valor = float(valor)
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if isinstance(valor, int):
        return f"{valor:,}".replace(",", ".")
    texto = f"{valor:,.{decimales}f}".rstrip("0").rstrip(".")
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _cambio(actual, anterior, mejor_si_baja=False, puntos=False):
    if anterior is None:
        return None
    dif = actual - anterior
    if dif == 0:
        return {"texto": "igual que el periodo anterior", "tono": "neutro"}
    bueno = (dif < 0) if mejor_si_baja else (dif > 0)
    signo = "+" if dif > 0 else "-"
    unidad = " puntos" if puntos else ""
    return {"texto": f"{signo}{_n(abs(dif))}{unidad} vs periodo anterior ({_n(anterior)}{' %' if puntos else ''})",
            "tono": "bueno" if bueno else "malo"}


class Filtros:
    def __init__(self, desde, hasta, rol="", solo_no=False, q=""):
        self.desde, self.hasta, self.rol, self.solo_no, self.q = desde, hasta, rol, solo_no, q
        dias = (hasta - desde).days + 1
        self.hasta_ant = desde - timedelta(days=1)
        self.desde_ant = self.hasta_ant - timedelta(days=dias - 1)

    def textos(self, con_rol=False):
        t = [f"Desde: {self.desde:%d/%m/%Y}", f"Hasta: {self.hasta:%d/%m/%Y}"]
        if con_rol:
            t.append(f"Rol: {ROLES[self.rol]['nombre'] if self.rol in ROLES else 'Todos'}")
            if self.q:
                t.append(f"Búsqueda: {self.q}")
        return t


def _movimientos(f, desde=None, hasta=None):
    qs = Movimiento.objects.select_related("usuario").filter(
        fecha__date__gte=desde or f.desde, fecha__date__lte=hasta or f.hasta)
    if f.rol in ROLES:
        qs = qs.filter(usuario__rol=f.rol)
    if f.q:
        qs = qs.filter(Q(accion__icontains=f.q) | Q(referencia__icontains=f.q) | Q(motivo__icontains=f.q))
    return qs


# ---------------------------------------------------------------------
def inventario(f):
    stock = stock_materiales()
    mats, bajos = [], 0
    for m in Material.objects.filter(activo=True).order_by("tipo", "nombre"):
        cant = stock.get(m.pk, Decimal("0"))
        bajo = cant < m.stock_minimo
        bajos += bajo
        mats.append([m.codigo, m.nombre, m.get_tipo_display(), f"{_n(cant)} {m.unidad}",
                     f"{_n(m.stock_minimo)} {m.unidad}", "Bajo el mínimo" if bajo else "Bien"])
    pt = inventario_producto_terminado()
    prods, bajos_pt = [], 0
    for t in Tamano.objects.filter(activo=True, producto__activo=True).select_related("producto__tipo"):
        u = pt.get(t.pk, 0)
        bajo = u < t.stock_minimo
        bajos_pt += bajo
        prods.append([t.codigo, str(t), f"{_n(u)} und", f"{_n(t.stock_minimo)} und", "Bajo el mínimo" if bajo else "Bien"])
    return {
        "titulo": "Inventario actual",
        "subtitulo": "Cuánto hay de cada cosa y qué está bajo el mínimo",
        "filtros": [f"Corte: {timezone.localtime():%d/%m/%Y %H:%M}"],
        "kpis": [
            {"valor": _n(len(mats)), "texto": "materiales activos"},
            {"valor": _n(bajos), "texto": "materiales bajo el mínimo"},
            {"valor": _n(len(prods)), "texto": "productos y tamaños"},
            {"valor": _n(bajos_pt), "texto": "productos bajo el mínimo"},
        ],
        "secciones": [
            {"titulo": "Materiales", "cabeceras": ["Código", "Material", "Tipo", "En inventario", "Stock mínimo", "Estado"], "filas": mats,
             "nota": "En inventario = lo aprobado por Calidad menos lo entregado a producción."},
            {"titulo": "Producto terminado", "cabeceras": ["Código", "Producto", "En bodega", "Stock mínimo", "Estado"], "filas": prods,
             "nota": "En bodega = lotes liberados por Calidad menos lo despachado."},
        ],
        "nota_final": (f"Para decidir: {bajos} material(es) necesitan compra." if bajos else "Todos los materiales están por encima del mínimo."),
    }


def movimientos(f, solo_no=None):
    solo_no = f.solo_no if solo_no is None else solo_no
    qs = _movimientos(f)
    if solo_no:
        qs = qs.filter(paso=False)
    total, no = qs.count(), qs.filter(paso=False).count()
    ant = _movimientos(f, f.desde_ant, f.hasta_ant)
    if solo_no:
        ant = ant.filter(paso=False)
    filas = [[f"{timezone.localtime(m.fecha):%d/%m/%Y %H:%M}", m.usuario.get_full_name() or m.usuario.username,
              m.usuario.get_rol_display(), m.accion, m.get_etapa_display(), "Pasó" if m.paso else "No pasó",
              m.motivo or ""] for m in qs.order_by("fecha")]
    return {
        "titulo": "Movimientos" if not solo_no else "Movimientos que no pasaron",
        "subtitulo": "El historial completo con los filtros elegidos",
        "filtros": f.textos(con_rol=True) + (["Solo lo que no pasó"] if solo_no else []),
        "kpis": [
            {"valor": _n(total), "texto": "movimientos", "cambio": _cambio(total, ant.count())},
            {"valor": _n(total - no), "texto": "pasaron"},
            {"valor": _n(no), "texto": "no pasaron", "cambio": _cambio(no, ant.filter(paso=False).count(), mejor_si_baja=True)},
            {"valor": f"{round(100 * (total - no) / total) if total else 0} %", "texto": "pasaron a la siguiente etapa"},
        ],
        "secciones": [{"titulo": "Detalle", "cabeceras": ["Fecha", "Quién", "Rol", "Qué hizo", "Etapa", "Resultado", "Motivo"],
                       "filas": filas, "ancho": [62, 70, 60, 170, 60, 42, 110]}],
        "nota_final": "Datos tomados del historial del sistema, que no se puede editar ni borrar.",
    }


def no_paso(f):
    qs = _movimientos(f).filter(paso=False).exclude(etapa="ADMINISTRACION")
    ant = _movimientos(f, f.desde_ant, f.hasta_ant).filter(paso=False).exclude(etapa="ADMINISTRACION")
    por_etapa = Counter(m.get_etapa_display() for m in qs)
    categorias = Counter(_categoria_no_conformidad(m) for m in qs)
    filas = [[f"{timezone.localtime(m.fecha):%d/%m/%Y %H:%M}", m.get_etapa_display(), m.referencia,
              m.accion, m.motivo, m.usuario.get_full_name() or m.usuario.username] for m in qs.order_by("fecha")]
    top = categorias.most_common(1)
    return {
        "titulo": "Lo que no pasó",
        "subtitulo": "Rechazos, devoluciones, órdenes detenidas y novedades, con su motivo",
        "filtros": f.textos(con_rol=True),
        "kpis": [
            {"valor": _n(len(filas)), "texto": "no pasaron", "cambio": _cambio(len(filas), ant.count(), mejor_si_baja=True)},
            {"valor": _n(len(por_etapa)), "texto": "etapas con problemas"},
            {"valor": top[0][0] if top else "—", "texto": "no conformidad más común", "pequeno": True},
        ],
        "secciones": [
            {"titulo": "Por etapa", "cabeceras": ["Etapa", "Veces"], "filas": [[e, _n(c)] for e, c in por_etapa.most_common()]},
            {"titulo": "Principales no conformidades", "cabeceras": ["No conformidad", "Veces"],
             "filas": [[c, _n(k)] for c, k in categorias.most_common(8)]},
            {"titulo": "Detalle", "cabeceras": ["Fecha", "Etapa", "Lote u orden", "Qué pasó", "Motivo", "Quién"],
             "filas": filas, "ancho": [62, 60, 60, 150, 150, 70]},
        ],
        "nota_final": (f"Para decidir: el problema más repetido es «{top[0][0]}» ({top[0][1]} veces)." if top else "No hubo no conformidades en el periodo."),
    }


def produccion(f):
    def ordenes(d, h):
        return OrdenProduccion.objects.filter(fecha__date__gte=d, fecha__date__lte=h).select_related(
            "tamano__producto__tipo", "operador", "cliente")
    actuales = list(ordenes(f.desde, f.hasta))
    pedido = sum(o.cantidad for o in actuales)
    producido = sum(o.registro.cantidad_producida for o in actuales if getattr(o, "registro", None))
    ant = list(ordenes(f.desde_ant, f.hasta_ant))
    prod_ant = sum(o.registro.cantidad_producida for o in ant if getattr(o, "registro", None))
    filas = []
    for o in actuales:
        reg = getattr(o, "registro", None)
        hecho = reg.cantidad_producida if reg else 0
        filas.append([o.codigo, f"{o.fecha:%d/%m/%Y}", str(o.tamano), _n(o.cantidad), _n(hecho) if reg else "—",
                      f"{round(100 * hecho / o.cantidad)} %" if reg else "—", o.get_estado_display(),
                      o.operador.get_full_name() or o.operador.username])
    usados = defaultdict(Decimal)
    unidades = {}
    for d in EntregaDetalle.objects.filter(entrega__fecha__date__gte=f.desde, entrega__fecha__date__lte=f.hasta).select_related("llegada__material"):
        usados[d.llegada.material.nombre] += d.cantidad
        unidades[d.llegada.material.nombre] = d.llegada.material.unidad
    cumplimiento = round(100 * producido / pedido) if pedido else 0
    return {
        "titulo": "Producción",
        "subtitulo": "Meta contra producido y materiales usados",
        "filtros": f.textos(),
        "kpis": [
            {"valor": _n(len(actuales)), "texto": "órdenes creadas", "cambio": _cambio(len(actuales), len(ant))},
            {"valor": _n(producido), "texto": "unidades producidas", "cambio": _cambio(producido, prod_ant)},
            {"valor": f"{cumplimiento} %", "texto": "cumplimiento (producido / pedido)"},
            {"valor": _n(sum(1 for o in actuales if o.estado in ("DETENIDA", "CON_NOVEDAD"))), "texto": "detenidas o con novedad"},
        ],
        "secciones": [
            {"titulo": "Órdenes", "cabeceras": ["Orden", "Fecha", "Producto", "Pedido", "Producido", "Cumplimiento", "Estado", "Operador"],
             "filas": filas, "ancho": [55, 50, 150, 40, 45, 55, 70, 80]},
            {"titulo": "Materiales entregados a producción", "cabeceras": ["Material", "Cantidad"],
             "filas": [[m, f"{_n(c)} {unidades[m]}"] for m, c in sorted(usados.items())]},
        ],
        "nota_final": "Cumplimiento = unidades producidas / unidades pedidas en las órdenes del periodo.",
    }


def proveedores(f):
    def resumen(d, h):
        datos = {}
        for p in Proveedor.objects.all():
            ll = Llegada.objects.filter(proveedor=p, fecha__date__gte=d, fecha__date__lte=h)
            total = ll.count()
            if not total:
                continue
            aprob = ll.filter(estado=Llegada.Estado.APROBADA).count()
            rech = ll.filter(estado=Llegada.Estado.RECHAZADA).count()
            dev = ll.filter(estado=Llegada.Estado.DEVUELTA).count()
            motivos = Counter()
            for x in ll.filter(estado=Llegada.Estado.RECHAZADA).select_related("revision"):
                rev = getattr(x, "revision", None)
                if rev and rev.motivo:
                    motivos[rev.motivo.split(";")[0].replace("Fuera de rango: ", "")[:60]] += 1
            if dev:
                motivos["Devuelto al llegar"] += dev
            revisadas = aprob + rech
            datos[p.pk] = {"p": p, "total": total, "aprob": aprob, "rech": rech, "dev": dev,
                           "pct": round(100 * aprob / revisadas) if revisadas else None,
                           "motivo": motivos.most_common(1)[0][0] if motivos else "—"}
        return datos
    act, ant = resumen(f.desde, f.hasta), resumen(f.desde_ant, f.hasta_ant)
    filas = [[d["p"].nombre, d["p"].nit, _n(d["total"]), _n(d["aprob"]), _n(d["rech"]), _n(d["dev"]),
              f"{d['pct']} %" if d["pct"] is not None else "—", d["motivo"]]
             for d in sorted(act.values(), key=lambda x: -x["total"])]
    tot = sum(d["total"] for d in act.values())
    aprob = sum(d["aprob"] for d in act.values())
    rech = sum(d["rech"] + d["dev"] for d in act.values())
    peor = min((d for d in act.values() if d["pct"] is not None), key=lambda x: x["pct"], default=None)
    return {
        "titulo": "Proveedores",
        "subtitulo": "Entregas, rechazos y motivos de cada proveedor",
        "filtros": f.textos(),
        "kpis": [
            {"valor": _n(len(act)), "texto": "proveedores con entregas"},
            {"valor": _n(tot), "texto": "entregas en el periodo", "cambio": _cambio(tot, sum(d["total"] for d in ant.values()))},
            {"valor": f"{round(100 * aprob / tot) if tot else 0} %", "texto": "aprobadas"},
            {"valor": _n(rech), "texto": "rechazadas o devueltas",
             "cambio": _cambio(rech, sum(d["rech"] + d["dev"] for d in ant.values()), mejor_si_baja=True)},
        ],
        "secciones": [{"titulo": "Desempeño por proveedor",
                       "cabeceras": ["Proveedor", "NIT", "Entregas", "Aprobadas", "Rechazadas", "Devueltas", "% aprobación", "Motivo principal"],
                       "filas": filas, "ancho": [100, 60, 45, 50, 55, 50, 55, 130]}],
        "nota_final": (f"Para decidir: {peor['p'].nombre} tiene la aprobación más baja ({peor['pct']} %)." if peor and peor["pct"] < 100
                       else "Todos los proveedores tuvieron 100 % de aprobación." if act else "No hubo entregas en el periodo."),
    }


def vencimientos(f):
    filas_d = lotes_por_vencer(30)
    filas = [[x["nombre"], x["tipo"], x["lote"], x["cantidad"], f"{x['vence']:%d/%m/%Y}",
              "Vencido" if x["dias"] < 0 else f"{x['dias']} días", x["accion"]] for x in filas_d]
    return {
        "titulo": "Vencimientos",
        "subtitulo": "Materiales y lotes de producto que vencen en los próximos 30 días",
        "filtros": [f"Corte: {timezone.localtime():%d/%m/%Y}"],
        "kpis": [
            {"valor": _n(sum(1 for x in filas_d if x["dias"] <= 7)), "texto": "vencen en 7 días o menos"},
            {"valor": _n(len(filas_d)), "texto": "vencen en 30 días"},
        ],
        "secciones": [{"titulo": "Lotes por vencer", "cabeceras": ["Producto o material", "Tipo", "Lote", "Cantidad", "Vence", "Faltan", "Qué hacer"],
                       "filas": filas, "ancho": [120, 75, 60, 60, 55, 45, 120]}],
        "nota_final": "Primero se usa o despacha lo que vence antes.",
    }


def despachos_cliente(f):
    def datos(d, h):
        clientes, productos = defaultdict(lambda: {"n": 0, "und": 0, "kg": Decimal("0"), "prod": Counter()}), Counter()
        detalle = defaultdict(lambda: defaultdict(lambda: [0, Decimal("0")]))
        for x in Despacho.objects.filter(fecha__date__gte=d, fecha__date__lte=h).select_related("cliente", "lote__tamano__producto__tipo"):
            kg = x.lote.tamano.peso_kg * x.cantidad
            c = clientes[x.cliente.nombre]
            c["n"] += 1
            c["und"] += x.cantidad
            c["kg"] += kg
            c["prod"][str(x.lote.tamano)] += x.cantidad
            productos[x.lote.tamano.producto.tipo.nombre] += kg
            detalle[x.cliente.nombre][str(x.lote.tamano)][0] += x.cantidad
            detalle[x.cliente.nombre][str(x.lote.tamano)][1] += kg
        return clientes, productos, detalle
    cli, prods, detalle = datos(f.desde, f.hasta)
    cli_ant, _, _ = datos(f.desde_ant, f.hasta_ant)
    total_kg = sum(c["kg"] for c in cli.values()) or Decimal("0")
    ranking = sorted(cli.items(), key=lambda x: -x[1]["kg"])
    filas = []
    for i, (nombre, c) in enumerate(ranking, 1):
        antes = cli_ant.get(nombre, {}).get("kg", Decimal("0")) if nombre in cli_ant else Decimal("0")
        dif = c["kg"] - antes
        filas.append([str(i), nombre, _n(c["n"]), _n(c["kg"]), f"{round(100 * c['kg'] / total_kg) if total_kg else 0} %",
                      ("+" if dif > 0 else "-" if dif < 0 else "=") + (_n(abs(dif)) if dif else ""), c["prod"].most_common(1)[0][0]])
    filas_det = []
    for nombre, _c in ranking[:3]:
        filas_det.append([f"» {nombre}", "", ""])
        for prod, (und, kg) in sorted(detalle[nombre].items(), key=lambda x: -x[1][1]):
            filas_det.append([prod, _n(und), _n(kg)])
    filas_prod = [[p, _n(kg), f"{round(100 * kg / total_kg) if total_kg else 0} %"] for p, kg in prods.most_common()]
    top2 = ranking[:2]
    pct2 = round(100 * sum(c["kg"] for _, c in top2) / total_kg) if total_kg else 0
    return {
        "titulo": "Despachos por cliente",
        "subtitulo": "A quién se despacha más y qué se lleva cada uno",
        "filtros": f.textos(),
        "kpis": [
            {"valor": _n(len(cli)), "texto": "clientes con despachos", "cambio": _cambio(len(cli), len(cli_ant))},
            {"valor": _n(sum(c["n"] for c in cli.values())), "texto": "despachos",
             "cambio": _cambio(sum(c["n"] for c in cli.values()), sum(c["n"] for c in cli_ant.values()))},
            {"valor": _n(total_kg), "texto": "kg / L despachados",
             "cambio": _cambio(total_kg, sum((c["kg"] for c in cli_ant.values()), Decimal("0")))},
            {"valor": ranking[0][0] if ranking else "—", "texto": "cliente principal", "pequeno": True},
        ],
        "secciones": [
            {"titulo": "Ranking de clientes", "cabeceras": ["#", "Cliente", "Despachos", "kg / L", "% del total", "vs periodo anterior", "Lo que más se lleva"],
             "filas": filas, "ancho": [18, 95, 50, 55, 50, 70, 165]},
            {"titulo": "Qué se lleva cada cliente (3 principales)", "cabeceras": ["Producto", "Unidades", "kg / L"], "filas": filas_det},
            {"titulo": "Productos más despachados", "cabeceras": ["Producto", "kg / L", "% del total"], "filas": filas_prod},
        ],
        "nota_final": ((f"Para decidir: los {len(top2)} clientes principales se llevan el {pct2} % de lo despachado. " if ranking else "")
                       + "Solo cuenta cantidades, no precios. Para poder sumar, 1 L de leche se cuenta como 1 kg."),
    }


REPORTES = {
    "inventario": ("Inventario actual", inventario),
    "movimientos": ("Movimientos", movimientos),
    "no-paso": ("Lo que no pasó", no_paso),
    "produccion": ("Producción", produccion),
    "proveedores": ("Proveedores", proveedores),
    "vencimientos": ("Vencimientos", vencimientos),
    "clientes": ("Despachos por cliente", despachos_cliente),
}
