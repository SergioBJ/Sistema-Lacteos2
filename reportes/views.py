from datetime import timedelta
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from catalogo.models import Material, Tamano, TipoProducto
from inventario.models import Despacho, Llegada, LoteProducto, Movimiento
from inventario.stock import lotes_disponibles, stock_materiales
from produccion.models import OrdenProduccion
from usuarios.menu import ROLES
from usuarios.permisos import rol_requerido

DIAS_ALERTA_VENCIMIENTO = 15
POR_PAGINA = 15  # movimientos por página en el historial


def inventario_producto_terminado():
    """{tamano_id: unidades en bodega} sumando el saldo de los lotes liberados."""
    E = LoteProducto.Estado
    total = {}
    lotes = LoteProducto.objects.filter(estado__in=[E.LIBERADO, E.DESPACHADO_PARCIAL]).annotate(
        despachado=Sum("despachos__cantidad"))
    for lote in lotes:
        total[lote.tamano_id] = total.get(lote.tamano_id, 0) + lote.cantidad - (lote.despachado or 0)
    return total


def lotes_por_vencer(dias=DIAS_ALERTA_VENCIMIENTO):
    hoy = timezone.localdate()
    limite = hoy + timedelta(days=dias)
    E = LoteProducto.Estado
    filas = []
    for lote in (LoteProducto.objects.filter(estado__in=[E.LIBERADO, E.DESPACHADO_PARCIAL, E.POR_LIBERAR],
                                              vencimiento__lte=limite)
                 .annotate(despachado=Sum("despachos__cantidad")).select_related("tamano__producto__tipo")):
        quedan = lote.cantidad - (lote.despachado or 0)
        if quedan > 0:
            filas.append({"tipo": "Producto terminado", "nombre": str(lote.tamano), "lote": lote.codigo,
                          "cantidad": f"{quedan} und", "vence": lote.vencimiento,
                          "dias": (lote.vencimiento - hoy).days, "ubicacion": lote.ubicacion})
    for material in Material.objects.filter(activo=True):
        for llegada, saldo in lotes_disponibles(material):
            if llegada.vencimiento <= limite:
                filas.append({"tipo": material.get_tipo_display(), "nombre": material.nombre,
                              "lote": llegada.lote_proveedor, "cantidad": f"{saldo:g} {material.unidad}",
                              "vence": llegada.vencimiento, "dias": (llegada.vencimiento - hoy).days,
                              "ubicacion": ""})
    for f in filas:
        f["accion"] = ("Usar o despachar hoy" if f["dias"] <= 3 else
                       "Priorizar en la próxima orden o despacho" if f["dias"] <= 7 else "Vigilar")
    return sorted(filas, key=lambda f: f["vence"])


@rol_requerido("GERENTE")
def resumen(request):
    hoy = timezone.localdate()
    E = OrdenProduccion.Estado
    mov_hoy = Movimiento.objects.filter(fecha__date=hoy)
    stock = stock_materiales()

    materiales = []
    for m in Material.objects.filter(activo=True).order_by("tipo", "nombre"):
        cant = stock.get(m.pk, Decimal("0"))
        materiales.append({"m": m, "stock": cant, "bajo": cant < m.stock_minimo})
    pt = inventario_producto_terminado()
    productos = []
    for t in Tamano.objects.filter(activo=True, producto__activo=True).select_related("producto__tipo"):
        unidades = pt.get(t.pk, 0)
        productos.append({"t": t, "unidades": unidades, "bajo": unidades < t.stock_minimo})
    por_vencer = lotes_por_vencer()

    activos = Count("parametros", filter=Q(parametros__activo=True))
    sin_param = (Material.objects.filter(activo=True).annotate(n=activos).filter(n=0).count()
                 + TipoProducto.objects.annotate(n=activos).filter(n=0).count())
    alertas = []
    bajos = [x for x in materiales if x["bajo"]]
    if bajos:
        alertas.append(("wa", f"{len(bajos)} material{'es' if len(bajos) > 1 else ''} bajo el stock mínimo: "
                        + ", ".join(x["m"].nombre for x in bajos[:4]) + ("…" if len(bajos) > 4 else "")))
    detenidas = OrdenProduccion.objects.filter(estado=E.DETENIDA).count()
    if detenidas:
        alertas.append(("no", f"{detenidas} orden{'es' if detenidas > 1 else ''} de producción detenida{'s' if detenidas > 1 else ''} por falta de material."))
    if por_vencer:
        alertas.append(("wa", f"{len(por_vencer)} lote{'s' if len(por_vencer) > 1 else ''} vence{'n' if len(por_vencer) > 1 else ''} en los próximos {DIAS_ALERTA_VENCIMIENTO} días."))
    if sin_param:
        alertas.append(("bl", f"{sin_param} material{'es' if sin_param > 1 else ''} o producto{'s' if sin_param > 1 else ''} sin parámetros de calidad."))

    pestana = request.GET.get("tab", "materiales")
    return render(request, "gerente/resumen.html", {
        "hoy": hoy,
        "kpi": {
            "movimientos": mov_hoy.count(),
            "no_paso": mov_hoy.filter(paso=False).count(),
            "llegadas": Llegada.objects.filter(fecha__date=hoy).count(),
            "en_curso": OrdenProduccion.objects.filter(estado__in=[E.ESPERANDO_MATERIALES, E.EN_PRODUCCION, E.POR_REVISAR]).count(),
            "despachos": Despacho.objects.filter(fecha__date=hoy).aggregate(t=Sum("cantidad"))["t"] or 0,
        },
        "alertas": alertas,
        "pestana": pestana,
        "materiales": materiales,
        "productos": productos,
        "por_vencer": por_vencer,
        "dias_alerta": DIAS_ALERTA_VENCIMIENTO,
        "ultimos": Movimiento.objects.select_related("usuario")[:8],
    })


@rol_requerido("GERENTE")
def historial(request):
    hoy = timezone.localdate()
    desde = parse_date(request.GET.get("desde", "") or "") or hoy.replace(day=1)
    hasta = parse_date(request.GET.get("hasta", "") or "") or hoy
    rol = request.GET.get("rol", "")
    solo_no = request.GET.get("solo") == "no"
    q = request.GET.get("q", "").strip()

    movs = Movimiento.objects.select_related("usuario").filter(fecha__date__gte=desde, fecha__date__lte=hasta)
    if rol in ROLES:
        movs = movs.filter(usuario__rol=rol)
    if solo_no:
        movs = movs.filter(paso=False)
    if q:
        movs = movs.filter(Q(accion__icontains=q) | Q(referencia__icontains=q) | Q(motivo__icontains=q)
                           | Q(usuario__first_name__icontains=q) | Q(usuario__username__icontains=q))

    total, no_paso = movs.count(), movs.filter(paso=False).count()
    pagina = Paginator(movs, POR_PAGINA).get_page(request.GET.get("pagina"))
    paginas = pagina.paginator.get_elided_page_range(pagina.number, on_each_side=1, on_ends=1)
    filtros = request.GET.copy()
    filtros.pop("pagina", None)
    return render(request, "gerente/historial.html", {
        "pagina": pagina,
        "desde": desde, "hasta": hasta, "rol": rol, "solo_no": solo_no, "q": q,
        "roles": [(k, v["nombre"], v["color"]) for k, v in ROLES.items()],
        "colores": {k: v["color"] for k, v in ROLES.items()},
        "total": total, "no_paso": no_paso,
        "filtros": filtros.urlencode(),
        "paginas": paginas,
    })


# =====================================================================
# Trazabilidad
# =====================================================================
from inventario.models import EntregaDetalle  # noqa: E402

COLORES = {k: v["color"] for k, v in ROLES.items()}


def _nombre(u):
    return u.get_full_name() or u.username


def _evento(fecha, rol, quien, titulo, detalle="", paso=True, tabla=None):
    return {"fecha": fecha, "color": COLORES.get(rol, "#6B7785"), "rol": ROLES.get(rol, {}).get("nombre", "Proveedor"),
            "quien": quien, "titulo": titulo, "detalle": detalle, "paso": paso, "tabla": tabla}


def recorrido_de_orden(orden):
    """Arma la línea de tiempo completa de una orden y su lote."""
    eventos, origen = [], []
    entrega = getattr(orden, "entrega", None)
    if entrega:
        for d in entrega.detalles.select_related("llegada__material", "llegada__proveedor", "llegada__revision__revisado_por"):
            ll = d.llegada
            rev = getattr(ll, "revision", None)
            origen.append({"material": ll.material.nombre, "lote": ll.lote_proveedor, "proveedor": ll.proveedor.nombre,
                           "cantidad": f"{d.cantidad:g} {ll.material.unidad}", "llegada": ll.fecha,
                           "aprobo": f"{_nombre(rev.revisado_por)} · {timezone.localtime(rev.fecha):%d/%m}" if rev else "—"})
    if origen:
        eventos.append(_evento(min(o["llegada"] for o in origen), "", f"{len(origen)} lote(s) de proveedor",
                               "Origen: materiales usados", "Todos aprobados por Calidad antes de usarse.",
                               tabla=origen))
    eventos.append(_evento(orden.fecha, "JEFE", _nombre(orden.creada_por), f"Orden {orden.codigo} creada",
                           f"{orden.cantidad} × {orden.tamano}" + (f" · cliente {orden.cliente}" if orden.cliente else "")
                           + f" · operador {_nombre(orden.operador)}"))
    if entrega:
        eventos.append(_evento(entrega.fecha, "ALMACENISTA", _nombre(entrega.entregado_por),
                               "Materiales entregados a producción", f"{len(origen)} lote(s) · se descontaron del inventario"))
    registro = getattr(orden, "registro", None)
    if registro:
        valores = list(registro.valores.all())
        en_rango = sum(1 for v in valores if v.dentro_rango)
        eventos.append(_evento(registro.inicio, "OPERADOR", _nombre(registro.operador), "Producción registrada",
                               f"{registro.cantidad_producida} unidades · limpieza {'hecha' if registro.limpieza_hecha else 'no confirmada'}"
                               f" · parámetros del proceso {en_rango} de {len(valores)} en rango"
                               + (f" · novedades: {registro.novedades}" if registro.novedades else "")))
        for r in registro.revisiones.select_related("revisado_por").order_by("fecha"):
            eventos.append(_evento(r.fecha, "JEFE", _nombre(r.revisado_por),
                                   "Producción aprobada" if r.aprobado else f"Producción con novedad · {r.get_accion_display()}",
                                   "Enviado a Calidad" if r.aprobado else f"{r.tipo_novedad}: {r.motivo}", r.aprobado))
    lote = getattr(orden, "lote", None)
    if lote:
        lib = getattr(lote, "liberacion", None)
        if lib:
            res = list(lib.resultados.all())
            ok = sum(1 for x in res if x.dentro_rango)
            eventos.append(_evento(lib.fecha, "CALIDAD", _nombre(lib.revisado_por),
                                   f"Lote {lote.codigo} liberado" if lib.liberado else f"Lote {lote.codigo} no conforme",
                                   f"Análisis {ok} de {len(res)} dentro del rango" + (f" · {lib.motivo}" if lib.motivo else ""),
                                   lib.liberado))
        for d in lote.despachos.select_related("cliente", "despachado_por"):
            eventos.append(_evento(d.fecha, "ALMACENISTA", _nombre(d.despachado_por), f"Despachado a {d.cliente}",
                                   f"{d.cantidad} unidades · factura {d.factura}"
                                   + (f" · vehículo {d.vehiculo}" if d.vehiculo else "")
                                   + (f" · conductor {d.conductor}" if d.conductor else "")))
    eventos.sort(key=lambda e: e["fecha"])
    return eventos, origen


@rol_requerido("GERENTE")
def trazabilidad(request):
    q = request.GET.get("q", "").strip()
    contexto = {"q": q, "recientes": LoteProducto.objects.order_by("-id")[:5]}
    if not q:
        return render(request, "gerente/trazabilidad.html", contexto)

    lote = LoteProducto.objects.filter(codigo__iexact=q).select_related("orden", "tamano__producto__tipo").first()
    orden = (lote.orden if lote else
             OrdenProduccion.objects.filter(codigo__iexact=q).select_related("tamano", "cliente", "operador", "creada_por").first())

    if orden:
        lote = getattr(orden, "lote", None)
        eventos, origen = recorrido_de_orden(orden)
        despachado = sum(d.cantidad for d in lote.despachos.all()) if lote else 0
        clientes = sorted({str(d.cliente) for d in lote.despachos.select_related("cliente")}) if lote else []
        contexto.update({
            "modo": "lote", "orden": orden, "lote": lote, "eventos": eventos, "origen": origen,
            "proveedores": sorted({o["proveedor"] for o in origen}),
            "despachado": despachado, "clientes": clientes,
            "operador": _nombre(orden.operador),
            "libero": _nombre(lote.liberacion.revisado_por) if lote and getattr(lote, "liberacion", None) else None,
        })
        return render(request, "gerente/trazabilidad.html", contexto)

    # Al revés: desde un lote de proveedor o una llegada, ver en qué terminó.
    llegadas = list(Llegada.objects.filter(Q(lote_proveedor__iexact=q) | Q(codigo__iexact=q))
                    .select_related("material", "proveedor", "registrado_por"))
    if llegadas:
        filas = []
        for ll in llegadas:
            rev = getattr(ll, "revision", None)
            usos = []
            for d in EntregaDetalle.objects.filter(llegada=ll).select_related(
                    "entrega__orden__tamano", "entrega__orden__lote"):
                o = d.entrega.orden
                lt = getattr(o, "lote", None)
                usos.append({"orden": o, "cantidad": f"{d.cantidad:g} {ll.material.unidad}", "lote": lt,
                             "clientes": sorted({str(x.cliente) for x in lt.despachos.select_related("cliente")}) if lt else []})
            filas.append({"ll": ll, "rev": rev, "usos": usos})
        contexto.update({"modo": "origen", "filas": filas})
        return render(request, "gerente/trazabilidad.html", contexto)

    contexto["no_encontrado"] = True
    return render(request, "gerente/trazabilidad.html", contexto)


# =====================================================================
# Gráficas
# =====================================================================
import re  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import date  # noqa: E402

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
ETAPAS_FLUJO = [
    ("RECEPCION", "1 · Recepción de materia prima e insumo"),
    ("REVISION", "2 · Revisión de calidad"),
    ("ORDEN", "3 · Orden de producción"),
    ("PRODUCCION", "4 · Producción"),
    ("LIBERACION", "5 · Liberación de producto terminado"),
]
NOMBRE_ETAPA = {"RECEPCION": "Recepción", "REVISION": "Calidad", "ORDEN": "Orden",
                "PRODUCCION": "Producción", "LIBERACION": "Liberación", "DESPACHO": "Despacho"}


def _mes(fecha_mes, delta):
    m = fecha_mes.month - 1 + delta
    return date(fecha_mes.year + m // 12, m % 12 + 1, 1)


def _categoria_no_conformidad(m):
    """Agrupa los motivos en categorías entendibles."""
    motivo = m.motivo or ""
    if m.etapa in ("REVISION", "LIBERACION"):
        hallado = re.search(r"Fuera de rango: ([^;(]+?) -?\d", motivo)
        if hallado:
            donde = "material" if m.etapa == "REVISION" else "producto terminado"
            return f"{hallado.group(1).strip()} fuera de rango en {donde}"
        return "Rechazo en revisión de material" if m.etapa == "REVISION" else "Lote no conforme"
    if m.etapa == "ORDEN":
        return "Falta material para la orden" if "Falta" in motivo else "Orden detenida"
    if m.etapa == "PRODUCCION":
        return motivo.split(":", 1)[0].strip() or "Novedad en producción"
    if m.etapa == "RECEPCION":
        return "Material devuelto al proveedor al llegar"
    return "Otra"


def _delta(actual, anterior, sufijo="", mejor_si_baja=False, es_puntos=False):
    if anterior is None:
        return None
    dif = actual - anterior
    if dif == 0:
        return {"texto": "igual que el mes anterior", "tono": "neutro"}
    sube = dif > 0
    bueno = (not sube) if mejor_si_baja else sube
    unidad = " puntos" if es_puntos else sufijo
    return {"texto": f"{'↑' if sube else '↓'} {abs(dif):g}{unidad} vs mes anterior ({anterior:g}{'%' if es_puntos else ''})",
            "tono": "bueno" if bueno else "malo"}


@rol_requerido("GERENTE")
def graficas(request):
    hoy = timezone.localdate()
    try:
        anio, mes = (int(x) for x in request.GET.get("periodo", "").split("-"))
        inicio = date(anio, mes, 1)
    except ValueError:
        inicio = hoy.replace(day=1)
    fin = _mes(inicio, 1) - timedelta(days=1)
    inicio_ant = _mes(inicio, -1)
    fin_ant = inicio - timedelta(days=1)
    rol = request.GET.get("rol", "")

    def movs(desde, hasta):
        qs = Movimiento.objects.filter(fecha__date__gte=desde, fecha__date__lte=hasta).exclude(etapa="ADMINISTRACION")
        if rol in ROLES:
            qs = qs.filter(usuario__rol=rol)
        return qs

    actual, anterior = movs(inicio, fin), movs(inicio_ant, fin_ant)
    n, n_ant = actual.count(), anterior.count()
    no, no_ant = actual.filter(paso=False).count(), anterior.filter(paso=False).count()
    pct = round(100 * (n - no) / n) if n else 0
    pct_ant = round(100 * (n_ant - no_ant) / n_ant) if n_ant else None

    stock = stock_materiales()
    compras = []
    for m in Material.objects.filter(activo=True):
        cant = stock.get(m.pk, Decimal("0"))
        if m.stock_minimo > 0 or cant > 0:
            compras.append({"m": m, "stock": cant, "minimo": m.stock_minimo, "bajo": cant < m.stock_minimo})
    compras.sort(key=lambda x: (not x["bajo"], x["m"].nombre))
    tope = max([max(x["stock"], x["minimo"]) for x in compras] or [Decimal("1")]) or Decimal("1")
    for x in compras:
        x["ancho"] = float(x["stock"] / tope * 100)
        x["linea"] = float(x["minimo"] / tope * 100)
    bajos = sum(1 for x in compras if x["bajo"])

    # 1. Entradas y salidas por semana del mes
    semanas = []
    d = inicio
    i = 1
    while d <= fin:
        h = min(d + timedelta(days=6), fin)
        semanas.append({"nombre": f"Sem {i}", "desde": d, "hasta": h,
                        "entradas": Llegada.objects.filter(fecha__date__gte=d, fecha__date__lte=h).count(),
                        "salidas": Despacho.objects.filter(fecha__date__gte=d, fecha__date__lte=h).count()})
        d, i = h + timedelta(days=1), i + 1
    tope_sem = max([max(s["entradas"], s["salidas"]) for s in semanas] or [1]) or 1
    for s in semanas:
        s["h_ent"] = round(s["entradas"] / tope_sem * 100)
        s["h_sal"] = round(s["salidas"] / tope_sem * 100)
    tot_ent, tot_sal = sum(s["entradas"] for s in semanas), sum(s["salidas"] for s in semanas)
    pico = max(semanas, key=lambda s: s["entradas"] + s["salidas"]) if semanas else None
    if tot_ent + tot_sal == 0:
        frase_sem = "Todavía no hay llegadas ni despachos en este mes."
    else:
        comp = ("entra más material del que sale" if tot_ent > tot_sal else
                "sale más de lo que entra" if tot_sal > tot_ent else "entra lo mismo que sale")
        frase_sem = f"En el mes {comp} ({tot_ent} llegadas y {tot_sal} despachos). La {pico['nombre'].lower().replace('sem', 'semana')} fue la de más movimiento."

    # 2. Etapas
    conteo = {e: {"total": 0, "no": 0} for e, _ in ETAPAS_FLUJO}
    for fila in actual.values("etapa", "paso"):
        if fila["etapa"] in conteo:
            conteo[fila["etapa"]]["total"] += 1
            conteo[fila["etapa"]]["no"] += 0 if fila["paso"] else 1
    etapas = []
    for clave, nombre in ETAPAS_FLUJO:
        c = conteo[clave]
        etapas.append({"nombre": nombre, "total": c["total"], "no": c["no"], "si": c["total"] - c["no"],
                       "pct_no": round(100 * c["no"] / c["total"]) if c["total"] else 0})
    peores = sorted([e for e in etapas if e["no"]], key=lambda e: -e["no"])[:2]
    if not peores:
        frase_etapas = "Todo lo que se registró este mes pasó a la siguiente etapa." if n else "Sin movimientos en este mes."
    else:
        partes = [f"{e['nombre'].split('· ')[1].lower()} ({e['no']} de {e['total']})" for e in peores]
        frase_etapas = "Donde más se frena es en " + " y en ".join(partes) + "."

    # 3. No conformidades
    categorias = Counter()
    etapa_de = {}
    for m in actual.filter(paso=False):
        cat = _categoria_no_conformidad(m)
        categorias[cat] += 1
        etapa_de.setdefault(cat, NOMBRE_ETAPA.get(m.etapa, m.etapa))
    top = categorias.most_common(6)
    tope_nc = top[0][1] if top else 1
    no_conformidades = [{"nombre": c, "n": k, "etapa": etapa_de[c], "ancho": round(k / tope_nc * 100)} for c, k in top]
    frase_nc = (f"El motivo más común es «{top[0][0]}» ({top[0][1]} vez{'es' if top[0][1] > 1 else ''})."
                if top else "No hubo no conformidades en este mes.")

    periodos = []
    p = hoy.replace(day=1)
    for _ in range(12):
        periodos.append((f"{p.year}-{p.month:02d}", f"{MESES[p.month - 1].capitalize()} {p.year}"))
        p = _mes(p, -1)

    return render(request, "gerente/graficas.html", {
        "periodo": f"{inicio.year}-{inicio.month:02d}", "periodos": periodos,
        "nombre_mes": f"{MESES[inicio.month - 1]} {inicio.year}",
        "rol": rol, "roles": [(k, v["nombre"]) for k, v in ROLES.items()],
        "kpis": [
            {"n": n, "texto": f"movimientos en {MESES[inicio.month - 1]}", "delta": _delta(n, n_ant)},
            {"n": f"{pct} %", "texto": "pasaron a la siguiente etapa",
             "delta": _delta(pct, pct_ant, es_puntos=True) if pct_ant is not None and n else None},
            {"n": no, "texto": "no pasaron", "delta": _delta(no, no_ant, mejor_si_baja=True)},
            {"n": bajos, "texto": "materiales bajo el mínimo", "delta": None},
        ],
        "semanas": semanas, "frase_sem": frase_sem,
        "etapas": etapas, "frase_etapas": frase_etapas,
        "no_conformidades": no_conformidades, "frase_nc": frase_nc,
        "compras": compras, "frase_compras": (f"{bajos} material{'es' if bajos != 1 else ''} no alcanza{'n' if bajos != 1 else ''} el stock mínimo: hay que comprar."
                                              if bajos else "Todos los materiales están por encima del mínimo."),
    })
