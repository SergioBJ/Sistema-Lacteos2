"""Los datos de cada reporte, en un formato común que luego se convierte a PDF o Excel (ver exportar.py).

Cada reporte devuelve un diccionario:
    titulo, subtitulo, filtros (lista de textos), kpis (lista de {valor, texto, cambio}),
    secciones (tablas {titulo, cabeceras, filas, alinear, ancho, leyenda, nota}
               o gráficos {tipo: "barras", titulo, items: [(texto, valor, texto_valor)], tono}),
    nota_final
"""
import calendar
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from catalogo.models import Material, Proveedor, Tamano
from inventario.models import Despacho, EntregaDetalle, Llegada, LoteProducto, Movimiento
from inventario.stock import stock_materiales
from produccion.models import OrdenProduccion, RevisionJefe
from usuarios.menu import ROLES

from .views import _categoria_no_conformidad, inventario_producto_terminado, lotes_por_vencer

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


# ---------------------------------------------------------------------
# Ayudas para las celdas
# ---------------------------------------------------------------------
def pill(texto, tono):
    return {"pill": texto, "tono": tono}


def barra(pct, tono, texto=None):
    return {"barra": pct, "tono": tono, "texto": texto if texto is not None else f"{pct} %"}


def dos(texto, sub="", negrita=True):
    return {"t": texto, "sub": sub, "b": negrita}


def neg(texto, tono=None):
    return {"t": texto, "b": True, "tono": tono}


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


def _pct(parte, total, decimales=0):
    if not total:
        return None
    valor = 100 * Decimal(parte) / Decimal(total)
    return round(float(valor), decimales) if decimales else round(float(valor))


def _plural(palabra, cantidad):
    palabra = (palabra or "und").lower()
    if cantidad == 1 or palabra.endswith("s") or palabra in ("und", "kg", "g", "l", "ml"):
        return palabra
    return palabra + ("es" if palabra[-1] not in "aeiou" else "s")


class Filtros:
    def __init__(self, desde, hasta, rol="", solo_no=False, q=""):
        self.desde, self.hasta, self.rol, self.solo_no, self.q = desde, hasta, rol, solo_no, q
        if desde.day == 1 and (hasta.year, hasta.month) == (desde.year, desde.month):
            # Un mes (o lo que va del mes): se compara con el mes anterior completo
            self.hasta_ant = desde - timedelta(days=1)
            self.desde_ant = self.hasta_ant.replace(day=1)
            self.nombre_ant = MESES[self.hasta_ant.month]
        else:
            dias = (hasta - desde).days + 1
            self.hasta_ant = desde - timedelta(days=1)
            self.desde_ant = self.hasta_ant - timedelta(days=dias - 1)
            self.nombre_ant = "el periodo anterior"

    def textos(self, con_rol=False):
        t = [f"Desde: {self.desde:%d/%m/%Y}", f"Hasta: {self.hasta:%d/%m/%Y}"]
        if con_rol:
            t.append(f"Rol: {ROLES[self.rol]['nombre'] if self.rol in ROLES else 'Todos'}")
            if self.q:
                t.append(f"Búsqueda: {self.q}")
        return t

    def cambio(self, actual, anterior, mejor_si_baja=False, puntos=False, neutro=False):
        """'↑ 5 más que agosto', '↓ 2 puntos vs agosto', '= igual que agosto'."""
        if anterior is None or actual is None:
            return None
        dif = actual - anterior
        if dif == 0:
            return {"texto": f"= igual que {self.nombre_ant}", "tono": "neutro"}
        sube = dif > 0
        flecha = "↑" if sube else "↓"
        if puntos:
            texto = f"{flecha} {_n(abs(dif))} punto{'s' if abs(dif) != 1 else ''} vs {self.nombre_ant}"
        else:
            texto = f"{flecha} {_n(abs(dif))} {'más' if sube else 'menos'} que {self.nombre_ant}"
        tono = "neutro" if neutro else ("bueno" if sube != mejor_si_baja else "malo")
        return {"texto": texto, "tono": tono}


def _movimientos(f, desde=None, hasta=None):
    from django.db.models import Q
    qs = Movimiento.objects.select_related("usuario").filter(
        fecha__date__gte=desde or f.desde, fecha__date__lte=hasta or f.hasta)
    if f.rol in ROLES:
        qs = qs.filter(usuario__rol=f.rol)
    if f.q:
        qs = qs.filter(Q(accion__icontains=f.q) | Q(referencia__icontains=f.q) | Q(motivo__icontains=f.q))
    return qs


def _quien(usuario):
    return usuario.get_full_name() or usuario.username


# =====================================================================
# 1. Inventario actual
# =====================================================================
def _estado_stock(cant, minimo):
    if cant <= 0:
        return pill("Agotado", "no")
    if cant < minimo:
        return pill("Bajo el mínimo", "wa")
    if not minimo:
        return pill("Sin mínimo", "ne")
    return pill("Suficiente", "ok")


def inventario(f):
    stock = stock_materiales()
    hoy = timezone.localdate()
    filas, comprar, producir = [], [], []
    items = bajos = 0
    estados = Counter()
    for tipo_valor, tipo_texto in Material.Tipo.choices:
        mats = list(Material.objects.filter(activo=True, tipo=tipo_valor).order_by("codigo"))
        if not mats:
            continue
        filas.append([f"» {tipo_texto}", "", "", "", "", ""])
        for m in mats:
            cant = stock.get(m.pk, Decimal("0"))
            items += 1
            if cant < m.stock_minimo:
                bajos += 1
                comprar.append(f"{m.nombre} (faltan {_n(m.stock_minimo - cant)} {m.unidad})")
            estado = _estado_stock(cant, m.stock_minimo)
            estados[estado["pill"]] += 1
            filas.append([m.codigo, m.nombre, m.unidad, neg(_n(cant)), _n(m.stock_minimo), estado])
    pt = inventario_producto_terminado()
    tamanos = list(Tamano.objects.filter(activo=True, producto__activo=True).select_related("producto__tipo")
                   .order_by("producto__tipo__nombre", "producto__marca", "cantidad"))
    if tamanos:
        filas.append(["» Producto terminado", "", "", "", "", ""])
    for t in tamanos:
        u = pt.get(t.pk, 0)
        items += 1
        if u < t.stock_minimo:
            bajos += 1
            producir.append(f"{t.producto} {t.empaque.lower()} {_n(t.cantidad)} {t.unidad}")
        estado = _estado_stock(u, t.stock_minimo)
        estados[estado["pill"]] += 1
        filas.append([t.codigo, str(t), _plural(t.empaque, 2), neg(_n(u)), _n(t.stock_minimo), estado])

    por_revisar = Llegada.objects.filter(estado=Llegada.Estado.ESPERANDO).count()
    vencen7 = sum(1 for x in lotes_por_vencer(7) if x["dias"] >= 0)
    partes = []
    if comprar:
        partes.append("Para comprar: " + ", ".join(comprar) + ".")
    if producir:
        partes.append("Para producir: " + ", ".join(producir) + ".")
    partes.append("Solo cuenta material aprobado por Calidad y lotes liberados.")
    return {
        "titulo": "Inventario actual",
        "subtitulo": f"Existencias al {hoy:%d/%m/%Y}",
        "filtros": ["Categoría: Todas", "Estado: Todos"],
        "kpis": [
            {"valor": _n(items), "texto": "ítems en el reporte"},
            {"valor": _n(bajos), "texto": "bajo el mínimo"},
            {"valor": _n(por_revisar), "texto": "materiales por revisar"},
            {"valor": _n(vencen7), "texto": "vencen en 7 días"},
        ],
        "secciones": [
            {"tipo": "dona", "titulo": "Estado del inventario", "centro": _n(items), "centro_texto": "ítems",
             "partes": [("Suficiente", estados["Suficiente"], "ok", "por encima del mínimo"),
                        ("Bajo el mínimo", estados["Bajo el mínimo"], "wa", "hay que reponer"),
                        ("Agotado", estados["Agotado"], "no", "no hay nada"),
                        ("Sin mínimo", estados["Sin mínimo"], "ne", "no tiene mínimo definido")],
             "nota": (f"{bajos} de {items} ítems ({_pct(bajos, items)} %) necesitan compra o producción. Abajo está el detalle."
                      if bajos else "Todo está por encima del mínimo.")},
            {"titulo": "Existencias por categoría", "cabeceras": ["Código", "Descripción", "Unidad", "Existencia", "Mínimo", "Estado"],
             "filas": filas, "alinear": "lllrrl", "ancho": [55, 205, 50, 65, 60, 85],
             "leyenda": [("Suficiente", "ok", "por encima del mínimo"), ("Bajo el mínimo", "wa", "hay que reponer"),
                         ("Agotado", "no", "no hay nada"), ("Sin mínimo", "ne", "no tiene mínimo definido")]},
        ],
        "nota_final": " ".join(partes),
    }


# =====================================================================
# 2. Movimientos
# =====================================================================
def _resultado(m):
    if m.etapa == Movimiento.Etapa.ADMINISTRACION:
        return pill("Registro", "ne")
    return pill("Pasó", "ok") if m.paso else pill("No pasó", "no")


def _entradas_salidas(f):
    """Gráfico de líneas: llegadas y despachos por semana (o por mes si el periodo es largo)."""
    tramos = []
    if (f.hasta - f.desde).days <= 70:
        inicio = f.desde
        while inicio <= f.hasta:
            fin = min(inicio + timedelta(days=6), f.hasta)
            texto = (f"{inicio.day}-{fin.day} {MESES[fin.month][:3]}" if inicio.month == fin.month
                     else f"{inicio.day} {MESES[inicio.month][:3]}-{fin.day} {MESES[fin.month][:3]}")
            tramos.append((f"Sem {len(tramos) + 1} · {texto}", inicio, fin))
            inicio = fin + timedelta(days=1)
        unidad = "semana"
    else:
        inicio = f.desde
        while inicio <= f.hasta:
            ultimo = inicio.replace(day=calendar.monthrange(inicio.year, inicio.month)[1])
            fin = min(ultimo, f.hasta)
            tramos.append((f"{MESES[inicio.month][:3].capitalize()} {inicio:%y}", inicio, fin))
            inicio = fin + timedelta(days=1)
        unidad = "mes"
    entradas = [Llegada.objects.filter(fecha__date__gte=d, fecha__date__lte=h).count() for _, d, h in tramos]
    salidas = [Despacho.objects.filter(fecha__date__gte=d, fecha__date__lte=h).count() for _, d, h in tramos]
    notas = []
    if any(entradas) or any(salidas):
        i = max(range(len(tramos)), key=lambda k: entradas[k] + salidas[k])
        if unidad == "semana":
            cual = "La semana con más movimiento fue la " + tramos[i][0].split(" · ")[0].replace("Sem ", "")
        else:
            cual = "El mes con más movimiento fue " + tramos[i][0]
        notas.append(f"{cual} ({entradas[i] + salidas[i]} entre llegadas y despachos).")
        mas_salidas = [tramos[k][0].split(" · ")[0] for k in range(len(tramos)) if salidas[k] > entradas[k]]
        if mas_salidas:
            notas.append(f"Salió más de lo que entró en: {', '.join(mas_salidas)}.")
    else:
        notas.append("No hubo llegadas ni despachos en el periodo.")
    return {"tipo": "lineas", "titulo": f"Entradas y salidas por {unidad}", "etiquetas": [t[0] for t in tramos],
            "series": [("Entradas (llegadas)", "bl", entradas), ("Salidas (despachos)", "wa", salidas)],
            "nota": " ".join(notas)}



def movimientos(f, solo_no=None):
    solo_no = f.solo_no if solo_no is None else solo_no
    qs = _movimientos(f)
    if solo_no:
        qs = qs.filter(paso=False)
    total, no = qs.count(), qs.filter(paso=False).count()
    ant = _movimientos(f, f.desde_ant, f.hasta_ant)
    if solo_no:
        ant = ant.filter(paso=False)
    entradas = Llegada.objects.filter(fecha__date__gte=f.desde, fecha__date__lte=f.hasta).count()
    entradas_ant = Llegada.objects.filter(fecha__date__gte=f.desde_ant, fecha__date__lte=f.hasta_ant).count()
    salidas = Despacho.objects.filter(fecha__date__gte=f.desde, fecha__date__lte=f.hasta).count()
    salidas_ant = Despacho.objects.filter(fecha__date__gte=f.desde_ant, fecha__date__lte=f.hasta_ant).count()
    filas = []
    for m in qs.order_by("fecha"):
        fecha = timezone.localtime(m.fecha)
        filas.append([dos(f"{fecha:%d/%m}", f"{fecha:%H:%M}", negrita=False),
                      dos(_quien(m.usuario), m.usuario.get_rol_display(), negrita=False),
                      m.accion, m.referencia or "—", _resultado(m), m.motivo or ""])
    return {
        "titulo": "Movimientos" if not solo_no else "Movimientos que no pasaron",
        "subtitulo": f"Del {f.desde:%d/%m/%Y} al {f.hasta:%d/%m/%Y}",
        "filtros": f.textos(con_rol=True) + ["Mostrar: " + ("Solo lo que no pasó" if solo_no else "Todo")],
        "kpis": [
            {"valor": _n(total), "texto": "movimientos", "cambio": f.cambio(total, ant.count(), neutro=True)},
            {"valor": _n(entradas), "texto": "entradas (llegadas)", "cambio": f.cambio(entradas, entradas_ant, neutro=True)},
            {"valor": _n(salidas), "texto": "salidas (despachos)", "cambio": f.cambio(salidas, salidas_ant, neutro=True)},
            {"valor": _n(no), "texto": "no pasaron",
             "cambio": f.cambio(no, ant.filter(paso=False).count(), mejor_si_baja=True)},
        ],
        "secciones": [_entradas_salidas(f),
                      {"titulo": "Detalle de movimientos", "cabeceras": ["Fecha", "Quién", "Acción", "Lote u orden", "Resultado", "Motivo"],
                       "filas": filas, "ancho": [42, 92, 158, 68, 64, 120],
                       "leyenda": [("Pasó", "ok", "siguió a la siguiente etapa"), ("No pasó", "no", "rechazo o detención"),
                                   ("Registro", "ne", "cambio administrativo")],
                       "vacio": "No hubo movimientos en el periodo."}],
        "nota_final": f"Mostrando {_n(total)} movimiento{'s' if total != 1 else ''}, de más antiguo a más reciente. "
                      "Datos tomados del historial del sistema, que no se puede editar ni borrar.",
    }


# =====================================================================
# 3. Lo que no pasó
# =====================================================================
ETAPAS_FLUJO = [
    ("RECEPCION", "1 · Llegada", "1 · Llegada"),
    ("REVISION", "2 · Revisión de calidad", "2 · Calidad"),
    ("ORDEN", "3 · Orden de producción", "3 · Orden"),
    ("PRODUCCION", "4 · Producción", "4 · Producción"),
    ("LIBERACION", "5 · Liberación", "5 · Liberación"),
    ("DESPACHO", "6 · Despacho", "6 · Despacho"),
]


def _que_se_hizo(m, revisiones_jefe):
    if m.etapa in ("RECEPCION", "REVISION"):
        return "Devuelto al proveedor"
    if m.etapa == "ORDEN":
        return "Orden detenida hasta tener material"
    if m.etapa == "PRODUCCION":
        if m.usuario.rol == "OPERADOR":
            return "Pasó al Jefe para revisar"
        candidatas = [r for r in revisiones_jefe.get(m.referencia, []) if abs((r.fecha - m.fecha).total_seconds()) < 120]
        if candidatas:
            return "Devuelto al operador" if candidatas[0].accion == RevisionJefe.Accion.DEVOLVER else "Orden detenida"
        return "Devuelto al operador o detenida"
    if m.etapa == "LIBERACION":
        return "Lote bloqueado"
    if m.etapa == "DESPACHO":
        return "No se despachó"
    return "—"


def no_paso(f):
    def base(d, h):
        return _movimientos(f, d, h).exclude(etapa="ADMINISTRACION")
    actuales = base(f.desde, f.hasta)
    anteriores = base(f.desde_ant, f.hasta_ant)
    qs = list(actuales.filter(paso=False).order_by("fecha"))
    n_ant = anteriores.filter(paso=False).count()

    revisadas = actuales.filter(etapa__in=["REVISION", "LIBERACION"]).count()
    rev_no = actuales.filter(etapa__in=["REVISION", "LIBERACION"], paso=False).count()
    revisadas_ant = anteriores.filter(etapa__in=["REVISION", "LIBERACION"]).count()
    rev_no_ant = anteriores.filter(etapa__in=["REVISION", "LIBERACION"], paso=False).count()
    pct = _pct(rev_no, revisadas)
    pct_ant = _pct(rev_no_ant, revisadas_ant)
    rech_cal = actuales.filter(etapa="REVISION", paso=False).count()
    rech_cal_ant = anteriores.filter(etapa="REVISION", paso=False).count()
    abiertas = OrdenProduccion.objects.filter(estado__in=["DETENIDA", "CON_NOVEDAD"]).count()

    por_etapa = Counter(m.etapa for m in qs)
    barras_etapa = [(texto, por_etapa.get(clave, 0), _n(por_etapa.get(clave, 0)))
                    for clave, texto, _ in ETAPAS_FLUJO if clave != "DESPACHO" or por_etapa.get(clave)]
    categorias = Counter(_categoria_no_conformidad(m) for m in qs)
    barras_motivo = [(cat, k, _n(k)) for cat, k in categorias.most_common(6)]

    revisiones_jefe = defaultdict(list)
    for r in RevisionJefe.objects.filter(aprobado=False, fecha__date__gte=f.desde, fecha__date__lte=f.hasta + timedelta(days=1)
                                         ).select_related("registro__orden"):
        revisiones_jefe[r.registro.orden.codigo].append(r)
    corto = {clave: c for clave, _, c in ETAPAS_FLUJO}
    filas = []
    for m in qs:
        fecha = timezone.localtime(m.fecha)
        accion = m.accion[:1].upper() + m.accion[1:]
        filas.append([dos(f"{fecha:%d/%m}", f"{fecha:%H:%M}", negrita=False), corto.get(m.etapa, m.get_etapa_display()),
                      dos(accion, m.referencia, negrita=False), neg(m.motivo or "—"), _quien(m.usuario),
                      _que_se_hizo(m, revisiones_jefe)])
    top = categorias.most_common(1)
    return {
        "titulo": "Lo que no pasó",
        "subtitulo": "Rechazos, detenciones y novedades",
        "filtros": f.textos(con_rol=True) + ["Etapa: Todas"],
        "kpis": [
            {"valor": _n(len(qs)), "texto": "no pasaron en el periodo", "cambio": f.cambio(len(qs), n_ant, mejor_si_baja=True)},
            {"valor": f"{_n(pct)} %" if pct is not None else "—", "texto": "de las revisiones de Calidad",
             "cambio": f.cambio(pct, pct_ant, mejor_si_baja=True, puntos=True)},
            {"valor": _n(rech_cal), "texto": "rechazos de material en Calidad",
             "cambio": f.cambio(rech_cal, rech_cal_ant, mejor_si_baja=True)},
            {"valor": _n(abiertas), "texto": "órdenes siguen detenidas o con novedad"},
        ],
        "secciones": [
            {"tipo": "barras", "titulo": "¿En qué etapa?", "items": barras_etapa, "tono": "no"},
            {"tipo": "barras", "titulo": "¿Por qué no pasó? (lo más repetido)", "items": barras_motivo, "tono": "wa",
             "nota": "" if barras_motivo else "No hubo no conformidades en el periodo."},
            {"titulo": "Detalle con motivo", "cabeceras": ["Fecha", "Etapa", "Qué pasó", "Motivo", "Registró", "Qué se hizo"],
             "filas": filas, "ancho": [42, 62, 128, 138, 80, 95], "vacio": "Todo pasó en el periodo."},
        ],
        "nota_final": (f"Lo más repetido: {top[0][0]} ({top[0][1]} {'vez' if top[0][1] == 1 else 'veces'})."
                       if top else "Lo más repetido: nada, no hubo no conformidades en el periodo."),
    }


# =====================================================================
# 4. Producción
# =====================================================================
def _estado_orden(o):
    lote = getattr(o, "lote", None)
    if lote is not None:
        E = LoteProducto.Estado
        return {
            E.LIBERADO: pill("Liberada", "ok"),
            E.DESPACHADO: pill("Despachada", "ne"),
            E.DESPACHADO_PARCIAL: pill("Despachada en parte", "ne"),
            E.POR_LIBERAR: pill("Esperando a Calidad", "bl"),
            E.NO_CONFORME: pill("No conforme", "no"),
        }.get(lote.estado, pill(lote.get_estado_display(), "ne"))
    E = OrdenProduccion.Estado
    return {
        E.DETENIDA: pill("Detenida", "no"),
        E.CON_NOVEDAD: pill("Con novedad", "wa"),
        E.ESPERANDO_MATERIALES: pill("Esperando materiales", "bl"),
        E.EN_PRODUCCION: pill("En producción", "bl"),
        E.POR_REVISAR: pill("Por revisar", "bl"),
        E.APROBADA: pill("Aprobada", "ok"),
    }.get(o.estado, pill(o.get_estado_display(), "ne"))


def produccion(f):
    def ordenes(d, h):
        return list(OrdenProduccion.objects.filter(fecha__date__gte=d, fecha__date__lte=h)
                    .select_related("tamano__producto__tipo", "operador", "registro", "lote").order_by("fecha"))

    def resumen(lista):
        con_registro = [o for o in lista if getattr(o, "registro", None)]
        cumplimientos = [100 * o.registro.cantidad_producida / o.cantidad for o in con_registro]
        return {
            "n": len(lista),
            "terminadas": sum(1 for o in lista if getattr(o, "lote", None)),
            "cumpl": round(sum(cumplimientos) / len(cumplimientos), 1) if cumplimientos else None,
            "detenidas": sum(1 for o in lista if o.estado in ("DETENIDA", "CON_NOVEDAD")),
        }

    actuales, anteriores = ordenes(f.desde, f.hasta), ordenes(f.desde_ant, f.hasta_ant)
    r, ra = resumen(actuales), resumen(anteriores)

    filas = []
    for o in actuales:
        reg = getattr(o, "registro", None)
        lote = getattr(o, "lote", None)
        cumpl = round(100 * reg.cantidad_producida / o.cantidad, 1) if reg else None
        filas.append([o.codigo, f"{o.tamano.producto.tipo.nombre} · {o.tamano.producto.marca} · {_n(o.tamano.cantidad)} {o.tamano.unidad}",
                      lote.codigo if lote else "—", f"{_n(o.cantidad)} {_plural(o.tamano.empaque, o.cantidad)}",
                      neg(_n(reg.cantidad_producida)) if reg else neg("—"),
                      neg(f"{_n(cumpl)} %", "ok" if cumpl >= 98 else "wa" if cumpl >= 90 else "no") if cumpl is not None else "—",
                      _estado_orden(o)])

    return {
        "titulo": "Producción",
        "subtitulo": "Meta y producido por orden",
        "filtros": f.textos() + ["Producto: Todos"],
        "kpis": [
            {"valor": _n(r["n"]), "texto": "órdenes en el periodo", "cambio": f.cambio(r["n"], ra["n"], neutro=True)},
            {"valor": _n(r["terminadas"]), "texto": "terminadas (con lote)", "cambio": f.cambio(r["terminadas"], ra["terminadas"])},
            {"valor": f"{_n(r['cumpl'])} %" if r["cumpl"] is not None else "—", "texto": "cumplimiento promedio",
             "cambio": f.cambio(r["cumpl"], ra["cumpl"], puntos=True)},
            {"valor": _n(r["detenidas"]), "texto": "detenidas o con novedad",
             "cambio": f.cambio(r["detenidas"], ra["detenidas"], mejor_si_baja=True)},
        ],
        "secciones": [
            {"titulo": "Órdenes de producción", "cabeceras": ["Orden", "Producto · tamaño", "Lote", "Meta", "Producido", "Cumplim.", "Estado"],
             "filas": filas, "alinear": "lllrrrl", "ancho": [62, 160, 58, 62, 55, 55, 100],
             "leyenda": [("Liberada", "ok", "lista para despachar"), ("Esperando a Calidad", "bl", "en proceso"),
                         ("Con novedad", "wa", "revisar"), ("Detenida", "no", "parada"), ("Despachada", "ne", "ya salió")],
             "vacio": "No se crearon órdenes en el periodo."},
        ],
        "nota_final": "Cumplimiento = producido ÷ meta de cada orden. Solo cuentan las órdenes creadas en el periodo.",
    }


# =====================================================================
# 5. Proveedores
# =====================================================================
def _tono_aprobacion(pct):
    if pct is None:
        return "ne"
    return "ok" if pct >= 95 else "wa" if pct >= 80 else "no"


def proveedores(f):
    def resumen(d, h):
        datos = {}
        for p in Proveedor.objects.all():
            ll = list(Llegada.objects.filter(proveedor=p, fecha__date__gte=d, fecha__date__lte=h)
                      .select_related("material", "revision"))
            if not ll:
                continue
            E = Llegada.Estado
            aprob = sum(1 for x in ll if x.estado == E.APROBADA)
            rech = sum(1 for x in ll if x.estado == E.RECHAZADA)
            dev = sum(1 for x in ll if x.estado == E.DEVUELTA)
            motivos = Counter()
            for x in ll:
                if x.estado == E.RECHAZADA:
                    rev = getattr(x, "revision", None)
                    texto = (rev.motivo if rev else "") or "Rechazado en Calidad"
                    motivos[texto.split(";")[0].replace("Fuera de rango: ", "").split(" (")[0][:60]] += 1
                elif x.estado == E.DEVUELTA:
                    motivos["Devuelto al llegar"] += 1
            revisadas = aprob + rech + dev
            por_material = defaultdict(lambda: {"total": Decimal("0"), "rech": Decimal("0"), "unidad": ""})
            for x in ll:
                pm = por_material[x.material.nombre]
                pm["total"] += x.cantidad
                pm["unidad"] = x.material.unidad
                if x.estado in (E.RECHAZADA, E.DEVUELTA):
                    pm["rech"] += x.cantidad
            datos[p.pk] = {"p": p, "total": len(ll), "aprob": aprob, "rech": rech + dev,
                           "pct": _pct(aprob, revisadas), "materiales": sorted({x.material.nombre for x in ll}),
                           "motivo": motivos.most_common(1)[0] if motivos else None, "por_material": por_material}
        return datos

    act, ant = resumen(f.desde, f.hasta), resumen(f.desde_ant, f.hasta_ant)
    orden = sorted(act.values(), key=lambda x: -x["total"])
    filas = [[neg(d["p"].nombre), _n(d["total"]), _n(d["aprob"]), _n(d["rech"]),
              barra(d["pct"], _tono_aprobacion(d["pct"])) if d["pct"] is not None else pill("Sin revisar", "ne"),
              f"{d['motivo'][0]} ({d['motivo'][1]})" if d["motivo"] else "—"] for d in orden]
    cantidades = []
    for d in orden:
        for nombre, pm in sorted(d["por_material"].items()):
            pct_r = _pct(pm["rech"], pm["total"], 1) or 0
            cantidades.append([d["p"].nombre, nombre, f"{_n(pm['total'])} {pm['unidad']}", f"{_n(pm['rech'])} {pm['unidad']}",
                               pill(f"{_n(pct_r)} % rechazado", "ok" if pct_r == 0 else "wa" if pct_r < 10 else "no")])

    def totales(datos):
        tot = sum(x["total"] for x in datos.values())
        aprob = sum(x["aprob"] for x in datos.values())
        rech = sum(x["rech"] for x in datos.values())
        return tot, rech, _pct(aprob, aprob + rech)
    tot, rech, pct = totales(act)
    tot_a, rech_a, pct_a = totales(ant)
    peor = min((d for d in act.values() if d["pct"] is not None), key=lambda x: x["pct"], default=None)
    mejor = max((d for d in act.values() if d["pct"] is not None), key=lambda x: (x["pct"], x["total"]), default=None)
    if peor and peor["pct"] < 100:
        decidir = (f"Para decidir: {peor['p'].nombre} tiene la aprobación más baja ({peor['pct']} %)"
                   + (f", sobre todo por «{peor['motivo'][0]}»" if peor["motivo"] else "") + ".")
        if mejor and mejor is not peor:
            decidir += f" {mejor['p'].nombre} tuvo {mejor['pct']} % de aprobación."
    elif act:
        decidir = "Para decidir: todos los proveedores tuvieron 100 % de aprobación."
    else:
        decidir = "No hubo entregas en el periodo."
    return {
        "titulo": "Proveedores",
        "subtitulo": "Entregas, rechazos y motivos por proveedor",
        "filtros": f.textos() + ["Tipo: Todos"],
        "kpis": [
            {"valor": _n(len(act)), "texto": "proveedores con entregas", "cambio": f.cambio(len(act), len(ant), neutro=True)},
            {"valor": _n(tot), "texto": "entregas en el periodo", "cambio": f.cambio(tot, tot_a, neutro=True)},
            {"valor": f"{pct} %" if pct is not None else "—", "texto": "aprobadas a la primera",
             "cambio": f.cambio(pct, pct_a, puntos=True)},
            {"valor": _n(rech), "texto": "rechazadas o devueltas", "cambio": f.cambio(rech, rech_a, mejor_si_baja=True)},
        ],
        "secciones": [
            {"titulo": "Desempeño por proveedor",
             "cabeceras": ["Proveedor", "Entregas", "Aprobadas", "Rechazadas", "% aprobación", "Motivo principal de rechazo"],
             "filas": filas, "alinear": "lrrrll", "ancho": [140, 52, 60, 64, 105, 125],
             "leyenda": [("95 % o más", "ok", "bien"), ("80 a 94 %", "wa", "vigilar"), ("menos de 80 %", "no", "plan de mejora")],
             "vacio": "No hubo entregas en el periodo."},
            {"titulo": "Cantidades entregadas y rechazadas por material",
             "cabeceras": ["Proveedor", "Material", "Entregado", "Rechazado", "Resultado"],
             "filas": cantidades, "alinear": "llrrl", "ancho": [150, 140, 80, 80, 100]},
        ],
        "nota_final": decidir,
    }


# =====================================================================
# 6. Vencimientos
# =====================================================================
def _vencidos_materiales():
    """Lotes de material aprobados, ya vencidos y con saldo (no se pueden usar)."""
    hoy = timezone.localdate()
    entregado = {x["llegada_id"]: x["t"] for x in EntregaDetalle.objects.filter(
        llegada__vencimiento__lt=hoy).values("llegada_id").annotate(t=Sum("cantidad"))}
    filas = []
    for ll in Llegada.objects.filter(estado=Llegada.Estado.APROBADA, vencimiento__lt=hoy).select_related("material"):
        saldo = ll.cantidad - entregado.get(ll.pk, Decimal("0"))
        if saldo > 0:
            filas.append({"tipo": ll.material.get_tipo_display(), "nombre": ll.material.nombre, "lote": ll.lote_proveedor,
                          "cantidad": f"{_n(saldo)} {ll.material.unidad}", "vence": ll.vencimiento,
                          "dias": (ll.vencimiento - hoy).days})
    return filas


def _faltan(dias):
    if dias < 0:
        return pill("Vencido", "no")
    if dias == 0:
        return pill("Vence hoy", "no")
    tono = "no" if dias <= 7 else "wa" if dias <= 15 else "ne"
    return pill(f"{dias} día{'s' if dias != 1 else ''}", tono)


def _que_hacer(x):
    producto = x["tipo"] == "Producto terminado"
    if x["dias"] < 0:
        return f"Venció hace {-x['dias']} día{'s' if x['dias'] != -1 else ''}. No usar ni despachar."
    if x["dias"] <= 7:
        return "Despachar primero" if producto else "Usar primero en la próxima orden"
    if x["dias"] <= 15:
        return "Ofrecer en los próximos despachos" if producto else "Planear su uso esta semana"
    return "Vigilar"


def vencimientos(f):
    dias_ventana = 30
    lista = [x for x in lotes_por_vencer(dias_ventana)]
    vistos = {(x["nombre"], x["lote"]) for x in lista}
    lista += [x for x in _vencidos_materiales() if (x["nombre"], x["lote"]) not in vistos]
    lista.sort(key=lambda x: x["vence"])
    filas = [[dos(x["nombre"], x["tipo"]), x["lote"], x["cantidad"], f"{x['vence']:%d/%m/%Y}", _faltan(x["dias"]), _que_hacer(x)]
             for x in lista]
    hoy = timezone.localdate()
    vencidos = sum(1 for x in lista if x["dias"] < 0)
    en7 = sum(1 for x in lista if 0 <= x["dias"] <= 7)
    en15 = sum(1 for x in lista if 8 <= x["dias"] <= 15)
    en30 = sum(1 for x in lista if 16 <= x["dias"] <= 30)
    return {
        "titulo": "Vencimientos",
        "subtitulo": "Materiales y producto que vencen pronto",
        "filtros": [f"Desde: {hoy:%d/%m/%Y}", f"Hasta: {hoy + timedelta(days=dias_ventana):%d/%m/%Y}", "Tipo: Todos"],
        "kpis": [
            {"valor": _n(vencidos), "texto": "ya vencidos con saldo"},
            {"valor": _n(en7), "texto": "vencen en 7 días o menos"},
            {"valor": _n(en15), "texto": "vencen en 8 a 15 días"},
            {"valor": _n(en30), "texto": "vencen en 16 a 30 días"},
        ],
        "secciones": [{"tipo": "dona", "titulo": "¿Cuándo vence?", "centro": _n(len(lista)),
                       "centro_texto": "lote" if len(lista) == 1 else "lotes",
                       "partes": [("Ya vencidos", vencidos, "no", "no usar ni despachar"),
                                  ("En 1 a 7 días", en7, "no", "usar o despachar ya"),
                                  ("En 8 a 15 días", en15, "wa", "planear su uso"),
                                  ("En 16 a 30 días", en30, "ne", "vigilar")],
                       "nota": (f"{vencidos + en7} de {len(lista)} lotes ({_pct(vencidos + en7, len(lista))} %) ya vencieron "
                                "o vencen en una semana o menos." if lista else f"Nada vence en los próximos {dias_ventana} días.")},
                      {"titulo": f"Próximos a vencer ({dias_ventana} días)",
                       "cabeceras": ["Ítem", "Lote", "Cantidad", "Vence", "Faltan", "Qué hacer"],
                       "filas": filas, "alinear": "llrlll", "ancho": [145, 68, 62, 62, 82, 140],
                       "leyenda": [("rojo", "no", "vencido o vence en 7 días o menos"), ("amarillo", "wa", "vence en 8 a 15 días"),
                                   ("gris", "ne", "vence en 16 a 30 días")],
                       "vacio": f"Nada vence en los próximos {dias_ventana} días."}],
        "nota_final": "Regla del sistema: al entregar materiales y al despachar, el sistema sugiere primero el lote que vence antes. "
                      "Los lotes de material vencidos no se pueden entregar a producción.",
    }


# =====================================================================
# 7. Despachos por cliente
# =====================================================================
def despachos_cliente(f):
    def datos(d, h):
        clientes = defaultdict(lambda: {"n": 0, "und": 0, "kg": Decimal("0"), "prod": Counter()})
        productos = defaultdict(lambda: {"kg": Decimal("0"), "unidad": "kg", "clientes": Counter()})
        detalle = defaultdict(lambda: defaultdict(lambda: [0, Decimal("0"), ""]))
        for x in Despacho.objects.filter(fecha__date__gte=d, fecha__date__lte=h).select_related("cliente", "lote__tamano__producto__tipo"):
            t = x.lote.tamano
            kg = t.peso_kg * x.cantidad
            c = clientes[x.cliente.nombre]
            c["n"] += 1
            c["und"] += x.cantidad
            c["kg"] += kg
            c["prod"][f"{t.producto.tipo.nombre} · {t.empaque.lower()} {_n(t.cantidad)} {t.unidad}"] += x.cantidad
            p = productos[t.producto.tipo.nombre]
            p["kg"] += kg
            p["unidad"] = "L" if t.unidad in ("L", "ml") else "kg"
            p["clientes"][x.cliente.nombre] += kg
            fila = detalle[x.cliente.nombre][(str(t.producto), f"{t.empaque} {_n(t.cantidad)} {t.unidad}")]
            fila[0] += x.cantidad
            fila[1] += kg
            fila[2] = _plural(t.empaque, 2)
        return clientes, productos, detalle

    cli, prods, detalle = datos(f.desde, f.hasta)
    cli_ant, _, _ = datos(f.desde_ant, f.hasta_ant)
    total_kg = sum((c["kg"] for c in cli.values()), Decimal("0"))
    total_ant = sum((c["kg"] for c in cli_ant.values()), Decimal("0"))
    ranking = sorted(cli.items(), key=lambda x: -x[1]["kg"])
    filas = []
    for i, (nombre, c) in enumerate(ranking, 1):
        antes = cli_ant[nombre]["kg"] if nombre in cli_ant else Decimal("0")
        dif = c["kg"] - antes
        vs = (neg(f"↑ {_n(dif)}", "ok") if dif > 0 else neg(f"↓ {_n(-dif)}", "no") if dif < 0 else neg("= igual", "ne"))
        pct = _pct(c["kg"], total_kg) or 0
        filas.append([str(i), neg(nombre), _n(c["n"]), neg(_n(c["kg"])), barra(pct, "azul"), vs, c["prod"].most_common(1)[0][0]])
    filas_det = []
    for nombre, c in ranking[:3]:
        filas_det.append([f"» {nombre}", "", "", neg(_n(c["kg"]), None)])
        for (prod, tam), (und, kg, empaque) in sorted(detalle[nombre].items(), key=lambda x: -x[1][1]):
            filas_det.append([prod, tam, f"{_n(und)} {empaque}", _n(kg)])
    filas_prod = []
    for nombre, p in sorted(prods.items(), key=lambda x: -x[1]["kg"]):
        pct = _pct(p["kg"], total_kg) or 0
        filas_prod.append([neg(nombre), f"{_n(p['kg'])} {p['unidad']}", barra(pct, "celeste"), p["clientes"].most_common(1)[0][0]])
    top2 = ranking[:2]
    pct2 = _pct(sum(c["kg"] for _, c in top2), total_kg) or 0
    principal = ranking[0] if ranking else None
    crecio = max(((n, c["kg"] - (cli_ant[n]["kg"] if n in cli_ant else 0)) for n, c in ranking), key=lambda x: x[1], default=None)
    nota = ""
    if ranking:
        nombres = " y ".join(n for n, _ in top2)
        nota = f"Para decidir: {nombres} se llevan el {pct2} % de lo despachado. "
        if crecio and crecio[1] > 0:
            nota += f"{crecio[0]} fue el que más creció (+{_n(crecio[1])}). "
    nota += "Solo cuenta lo despachado: no maneja precios. Para poder sumar, 1 L de leche se cuenta como 1 kg."
    return {
        "titulo": "Despachos por cliente",
        "subtitulo": "A quién se despacha más y qué se lleva cada uno",
        "filtros": f.textos() + ["Cliente: Todos", "Producto: Todos"],
        "kpis": [
            {"valor": _n(len(cli)), "texto": "clientes con despachos", "cambio": f.cambio(len(cli), len(cli_ant), neutro=True)},
            {"valor": _n(sum(c["n"] for c in cli.values())), "texto": "despachos en el periodo",
             "cambio": f.cambio(sum(c["n"] for c in cli.values()), sum(c["n"] for c in cli_ant.values()))},
            {"valor": _n(total_kg), "texto": "kg / L despachados", "cambio": f.cambio(total_kg, total_ant)},
            {"valor": principal[0] if principal else "—",
             "texto": f"cliente principal · {_pct(principal[1]['kg'], total_kg)} %" if principal else "cliente principal",
             "pequeno": len(principal[0]) > 10 if principal else False},
        ],
        "secciones": [
            {"titulo": "Ranking de clientes", "cabeceras": ["#", "Cliente", "Despachos", "kg / L", "% del total", f"vs {f.nombre_ant}", "Lo que más se lleva"],
             "filas": filas, "alinear": "llrrlll", "ancho": [18, 82, 58, 52, 100, 62, 145],
             "vacio": "No hubo despachos en el periodo."},
            {"titulo": "Qué se lleva cada cliente (3 principales)", "cabeceras": ["Producto", "Tamaño", "Unidades", "kg / L"],
             "filas": filas_det, "alinear": "llrr", "ancho": [210, 110, 90, 70]},
            {"titulo": "Productos más despachados (todos los clientes)", "cabeceras": ["Producto", "Cantidad", "% del total", "Cliente que más lo pide"],
             "filas": filas_prod, "alinear": "lrll", "ancho": [150, 80, 130, 120]},
        ],
        "nota_final": nota,
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
