from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalogo.models import Material, Producto, Tamano
from inventario.historial import registrar
from usuarios.permisos import rol_requerido

from .calculo import faltantes_de_formula, revisar_disponibilidad, texto_faltantes
from .forms import FilaFormulaForm, NuevaOrdenForm
from .models import FormulaEmpaque, FormulaLimpieza, FormulaMateria, OrdenProduccion


def siguiente_codigo_orden():
    prefijo = f"OP-{timezone.localdate().year}-"
    n = OrdenProduccion.objects.filter(codigo__startswith=prefijo).count() + 1
    while OrdenProduccion.objects.filter(codigo=f"{prefijo}{n:03d}").exists():
        n += 1
    return f"{prefijo}{n:03d}"


# =====================================================================
# Mis órdenes
# =====================================================================
@rol_requerido("JEFE")
def ordenes(request):
    E = OrdenProduccion.Estado
    todas = OrdenProduccion.objects.select_related("tamano__producto__tipo", "cliente", "operador")
    return render(request, "jefe/ordenes.html", {
        "atencion": todas.filter(estado__in=[E.POR_REVISAR, E.DETENIDA]),
        "resto": todas.exclude(estado__in=[E.POR_REVISAR, E.DETENIDA])[:50],
    })


@rol_requerido("JEFE")
@require_POST
def orden_reintentar(request, pk):
    """Vuelve a revisar si ya alcanzan los materiales de una orden detenida."""
    orden = get_object_or_404(OrdenProduccion, pk=pk, estado=OrdenProduccion.Estado.DETENIDA)
    filas = revisar_disponibilidad(orden.tamano, orden.cantidad, excluir_orden=orden)
    faltan = texto_faltantes(filas)
    if faltan:
        messages.error(request, f"{orden.codigo} sigue detenida. {faltan}.")
        return redirect("jefe_ordenes")
    with transaction.atomic():
        orden.estado = OrdenProduccion.Estado.ESPERANDO_MATERIALES
        orden.motivo_detenida = ""
        orden.save(update_fields=["estado", "motivo_detenida"])
        registrar(request.user, "ORDEN", f"reactivó la orden {orden.codigo}: ya alcanzan los materiales",
                  True, orden.codigo)
    messages.success(request, f"{orden.codigo} ya tiene materiales. Quedó esperando la entrega del Almacenista.")
    return redirect("jefe_ordenes")


# =====================================================================
# Nueva orden (etapa 3)
# =====================================================================
@rol_requerido("JEFE")
def nueva_orden(request):
    filas, problemas = None, []
    if request.method == "POST":
        form = NuevaOrdenForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            problemas = faltantes_de_formula(d["tamano"])
            if not problemas:
                filas = revisar_disponibilidad(d["tamano"], d["cantidad"])
                if "crear" in request.POST:
                    faltan = texto_faltantes(filas)
                    with transaction.atomic():
                        orden = OrdenProduccion.objects.create(
                            codigo=siguiente_codigo_orden(), tamano=d["tamano"], cantidad=d["cantidad"],
                            cliente=d["cliente"], operador=d["operador"], creada_por=request.user,
                            estado=OrdenProduccion.Estado.DETENIDA if faltan else OrdenProduccion.Estado.ESPERANDO_MATERIALES,
                            motivo_detenida=faltan,
                        )
                        registrar(request.user, "ORDEN",
                                  f"creó la orden {orden.codigo} · {orden.cantidad} × {orden.tamano}"[:255],
                                  not faltan, orden.codigo, faltan)
                    if faltan:
                        messages.error(request, f"La orden {orden.codigo} se guardó como DETENIDA. {faltan}.")
                    else:
                        messages.success(request, f"Orden {orden.codigo} creada. El Almacenista ya puede entregar los materiales.")
                    return redirect("jefe_ordenes")
    else:
        form = NuevaOrdenForm()

    tamanos = Tamano.objects.filter(activo=True, producto__activo=True).select_related("producto")
    con_empaque = set(FormulaEmpaque.objects.values_list("tamano_id", flat=True))
    datos_tamanos = {
        str(t.pk): {"producto": t.producto_id, "con_empaque": t.pk in con_empaque} for t in tamanos
    }
    return render(request, "jefe/nueva.html", {
        "form": form,
        "filas": filas,
        "problemas": problemas,
        "todo_alcanza": filas is not None and all(f["alcanza"] for f in filas),
        "datos_tamanos": datos_tamanos,
        "proximo_codigo": siguiente_codigo_orden(),
    })


# =====================================================================
# Fórmulas de productos
# =====================================================================
SECCIONES = {
    "materia": {"modelo": FormulaMateria, "tipo": Material.Tipo.MATERIA_PRIMA, "campo": "cantidad_por_kg"},
    "empaque": {"modelo": FormulaEmpaque, "tipo": Material.Tipo.EMPAQUE, "campo": "cantidad_por_unidad"},
    "limpieza": {"modelo": FormulaLimpieza, "tipo": Material.Tipo.DESINFECTANTE, "campo": "cantidad_por_orden"},
}


@rol_requerido("JEFE")
def formulas(request):
    productos = Producto.objects.filter(activo=True).select_related("tipo").prefetch_related("tamanos")
    producto = None
    if request.GET.get("producto"):
        producto = get_object_or_404(Producto, pk=request.GET["producto"])

    if producto and request.method == "POST":
        seccion = request.POST.get("seccion")
        cfg = SECCIONES.get(seccion)
        if cfg:
            datos = request.POST.copy()
            datos["cantidad"] = datos.get("cantidad", "").strip().replace(",", ".")
            form = FilaFormulaForm(datos, tipo_material=cfg["tipo"])
            tamano = None
            if seccion == "empaque":
                tamano = get_object_or_404(Tamano, pk=request.POST.get("tamano"), producto=producto)
            if form.is_valid():
                material, cantidad = form.cleaned_data["material"], form.cleaned_data["cantidad"]
                destino = {"tamano": tamano} if tamano else {"producto": producto}
                with transaction.atomic():
                    cfg["modelo"].objects.update_or_create(
                        material=material, **destino, defaults={cfg["campo"]: cantidad})
                    donde = f"{tamano}" if tamano else f"{producto}"
                    registrar(request.user, "ORDEN",
                              f"actualizó la fórmula de {donde}: {material.nombre} = {cantidad:g}"[:255],
                              True, f"PROD-{producto.pk}")
                messages.success(request, f"Fórmula actualizada: {material.nombre}.")
            else:
                messages.error(request, "Elige el material y escribe una cantidad mayor que cero.")
        return redirect(f"{request.path}?producto={producto.pk}")

    contexto = {"productos": productos, "producto": producto}
    if producto:
        contexto.update({
            "materias": FormulaMateria.objects.filter(producto=producto).select_related("material"),
            "limpiezas": FormulaLimpieza.objects.filter(producto=producto).select_related("material"),
            "tamanos": [
                {"t": t, "filas": FormulaEmpaque.objects.filter(tamano=t).select_related("material")}
                for t in producto.tamanos.filter(activo=True)
            ],
            "mat_materia": Material.objects.filter(activo=True, tipo=Material.Tipo.MATERIA_PRIMA),
            "mat_empaque": Material.objects.filter(activo=True, tipo=Material.Tipo.EMPAQUE),
            "mat_limpieza": Material.objects.filter(activo=True, tipo=Material.Tipo.DESINFECTANTE),
        })
    return render(request, "jefe/formulas.html", contexto)


@rol_requerido("JEFE")
@require_POST
def formula_quitar(request, seccion, pk):
    cfg = SECCIONES.get(seccion)
    if not cfg:
        return redirect("jefe_formulas")
    fila = get_object_or_404(cfg["modelo"], pk=pk)
    producto = fila.tamano.producto if seccion == "empaque" else fila.producto
    with transaction.atomic():
        registrar(request.user, "ORDEN", f"quitó {fila.material.nombre} de la fórmula de {producto}"[:255],
                  True, f"PROD-{producto.pk}")
        fila.delete()
    messages.success(request, "Se quitó el material de la fórmula.")
    return redirect(f"/jefe/formulas/?producto={producto.pk}")


# =====================================================================
# Operador: Mi orden de hoy y Registrar producción (etapa 4)
# =====================================================================
from datetime import datetime  # noqa: E402
from decimal import InvalidOperation  # noqa: E402

from .models import RegistroProduccion, ValorProceso  # noqa: E402
from .proceso import PARAMETROS_PROCESO  # noqa: E402


def _num(texto):
    texto = (texto or "").strip().replace(" ", "").replace(",", ".")
    if not texto:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _fecha_hora(texto):
    try:
        return timezone.make_aware(datetime.strptime(texto, "%Y-%m-%dT%H:%M"))
    except (TypeError, ValueError):
        return None


@rol_requerido("OPERADOR")
def operador_orden(request):
    E = OrdenProduccion.Estado
    mias = (OrdenProduccion.objects.filter(operador=request.user)
            .select_related("tamano__producto__tipo", "cliente")
            .prefetch_related("entrega__detalles__llegada__material"))
    return render(request, "operador/orden.html", {
        "en_curso": mias.filter(estado=E.EN_PRODUCCION),
        "esperando": mias.filter(estado=E.ESPERANDO_MATERIALES),
        "enviadas": mias.filter(estado__in=[E.POR_REVISAR, E.APROBADA, E.CON_NOVEDAD]).order_by("-fecha")[:10],
    })


@rol_requerido("OPERADOR")
def operador_registro(request):
    E = OrdenProduccion.Estado
    pendientes = OrdenProduccion.objects.filter(operador=request.user, estado=E.EN_PRODUCCION).select_related("tamano")
    orden = None
    if request.GET.get("orden"):
        orden = get_object_or_404(pendientes, pk=request.GET["orden"])
    elif pendientes.count() == 1:
        orden = pendientes.first()

    errores, valores, datos = [], {}, {}
    registro_previo = getattr(orden, "registro", None) if orden else None

    if orden and request.method == "POST":
        datos = request.POST
        limpieza = datos.get("limpieza") == "1"
        inicio, fin = _fecha_hora(datos.get("inicio")), _fecha_hora(datos.get("fin"))
        try:
            producida = int(datos.get("cantidad", ""))
        except ValueError:
            producida = None
        novedades = datos.get("novedades", "").strip()

        if not limpieza:
            errores.append("Confirma que hiciste la limpieza: sin limpieza no se puede registrar.")
        if not inicio or not fin:
            errores.append("Escribe la hora de inicio y de fin.")
        elif fin <= inicio:
            errores.append("La hora de fin debe ser después de la de inicio.")
        if producida is None or producida < 0:
            errores.append("Escribe cuántas unidades se produjeron.")
        for i, (nombre, minimo, maximo, unidad) in enumerate(PARAMETROS_PROCESO):
            v = _num(datos.get(f"proc_{i}"))
            valores[i] = datos.get(f"proc_{i}", "")
            if v is None:
                errores.append(f"Falta el valor de {nombre}.")
        if producida is not None and producida < orden.cantidad and not novedades:
            errores.append(f"Se produjo menos de lo pedido ({producida} de {orden.cantidad}): explica por qué en Novedades.")

        if not errores:
            with transaction.atomic():
                registro, _ = RegistroProduccion.objects.update_or_create(
                    orden=orden,
                    defaults={"operador": request.user, "inicio": inicio, "fin": fin, "limpieza_hecha": True,
                              "cantidad_producida": producida, "novedades": novedades},
                )
                registro.valores.all().delete()
                fuera = []
                for i, (nombre, minimo, maximo, unidad) in enumerate(PARAMETROS_PROCESO):
                    v = _num(datos.get(f"proc_{i}"))
                    dentro = minimo <= v <= maximo
                    if not dentro:
                        fuera.append(nombre)
                    ValorProceso.objects.create(registro=registro, nombre=nombre, valor=v, minimo=minimo,
                                                maximo=maximo, unidad=unidad, dentro_rango=dentro)
                orden.estado = E.POR_REVISAR
                orden.save(update_fields=["estado"])
                verbo = "corrigió el registro y reenvió" if registro_previo else "registró"
                registrar(request.user, "PRODUCCION",
                          (f"{verbo} {producida} unidades producidas ({orden.codigo})"
                          + (f" · fuera de rango: {', '.join(fuera)}" if fuera else ""))[:255],
                          True, orden.codigo, novedades)
            messages.success(request, f"Producción de {orden.codigo} enviada al Jefe de Producción para su revisión.")
            return redirect("operador_orden")
    elif orden and registro_previo:
        # La orden fue devuelta por el Jefe: se precarga lo que ya se había registrado.
        datos = {
            "inicio": timezone.localtime(registro_previo.inicio).strftime("%Y-%m-%dT%H:%M"),
            "fin": timezone.localtime(registro_previo.fin).strftime("%Y-%m-%dT%H:%M"),
            "cantidad": registro_previo.cantidad_producida,
            "novedades": registro_previo.novedades,
        }
        previos = {v.nombre: v.valor for v in registro_previo.valores.all()}
        valores = {i: (f"{previos[n]:g}" if n in previos else "") for i, (n, *_r) in enumerate(PARAMETROS_PROCESO)}

    ultima_revision = registro_previo.revisiones.order_by("-fecha").first() if registro_previo else None
    return render(request, "operador/registro.html", {
        "orden": orden,
        "pendientes": pendientes,
        "parametros": [
            {"i": i, "nombre": n, "minimo": mn, "maximo": mx, "unidad": u, "valor": valores.get(i, "")}
            for i, (n, mn, mx, u) in enumerate(PARAMETROS_PROCESO)
        ],
        "errores": errores,
        "datos": datos,
        "devuelta": ultima_revision if ultima_revision and not ultima_revision.aprobado else None,
    })


# =====================================================================
# Jefe: Revisar producción (etapa 4)
# =====================================================================
import calendar  # noqa: E402

from inventario.models import LoteProducto  # noqa: E402

from .models import RevisionJefe  # noqa: E402

TIPOS_NOVEDAD = [
    "Parámetro del proceso fuera de rango",
    "Cantidad menor a la pedida",
    "Limpieza no confirmada o mal hecha",
    "Falla de equipo",
    "Producto dañado",
    "Otra",
]


def sumar_meses(fecha, meses):
    mes = fecha.month - 1 + meses
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return fecha.replace(year=anio, month=mes, day=dia)


def siguiente_codigo_lote():
    prefijo = f"L-{timezone.localdate().year}-"
    n = LoteProducto.objects.filter(codigo__startswith=prefijo).count() + 1
    while LoteProducto.objects.filter(codigo=f"{prefijo}{n:03d}").exists():
        n += 1
    return f"{prefijo}{n:03d}"


@rol_requerido("JEFE")
def revisar_lista(request):
    por_revisar = (OrdenProduccion.objects.filter(estado=OrdenProduccion.Estado.POR_REVISAR)
                   .select_related("tamano__producto__tipo", "operador", "registro").order_by("fecha"))
    return render(request, "jefe/revisar_lista.html", {"por_revisar": por_revisar})


@rol_requerido("JEFE")
def revisar(request, pk):
    orden = get_object_or_404(
        OrdenProduccion.objects.select_related("tamano__producto__tipo", "operador", "cliente"), pk=pk)
    registro = getattr(orden, "registro", None)
    if orden.estado != OrdenProduccion.Estado.POR_REVISAR or registro is None:
        messages.error(request, f"La orden {orden.codigo} no está esperando revisión.")
        return redirect("jefe_revisar")

    valores = list(registro.valores.all())
    fuera = [v for v in valores if not v.dentro_rango]
    menos = registro.cantidad_producida < orden.cantidad
    errores = []
    datos = {}

    if request.method == "POST":
        datos = request.POST
        accion = datos.get("accion")
        if accion == "aprobar":
            if registro.cantidad_producida <= 0:
                errores.append("No se produjo nada: no se puede aprobar. Márcala con novedad.")
            else:
                with transaction.atomic():
                    RevisionJefe.objects.create(registro=registro, revisado_por=request.user, aprobado=True)
                    fecha = timezone.localtime(registro.fin).date()
                    lote = LoteProducto.objects.create(
                        codigo=siguiente_codigo_lote(), orden=orden, tamano=orden.tamano,
                        cantidad=registro.cantidad_producida, fecha_produccion=fecha,
                        vencimiento=sumar_meses(fecha, orden.tamano.producto.vida_util_meses),
                    )
                    orden.estado = OrdenProduccion.Estado.APROBADA
                    orden.save(update_fields=["estado"])
                    registrar(request.user, "PRODUCCION",
                              f"aprobó la producción de {orden.codigo}: lote {lote.codigo} con "
                              f"{lote.cantidad} unidades, enviado a Calidad"[:255], True, lote.codigo)
                messages.success(request, f"Producción aprobada. Se creó el lote {lote.codigo} y quedó esperando a Calidad.")
                return redirect("jefe_ordenes")
        elif accion == "novedad":
            tipo = datos.get("tipo_novedad", "")
            motivo = datos.get("motivo", "").strip()
            que_hacer = datos.get("que_hacer")
            if tipo not in TIPOS_NOVEDAD:
                errores.append("Elige el tipo de novedad.")
            if not motivo:
                errores.append("Explica por qué no pasó: es obligatorio.")
            if que_hacer not in ("DEVOLVER", "DETENER"):
                errores.append("Elige qué se hace: devolver al operador o detener la orden.")
            if not errores:
                with transaction.atomic():
                    RevisionJefe.objects.create(registro=registro, revisado_por=request.user, aprobado=False,
                                                tipo_novedad=tipo, motivo=motivo, accion=que_hacer)
                    if que_hacer == "DEVOLVER":
                        orden.estado = OrdenProduccion.Estado.EN_PRODUCCION
                        texto = f"devolvió al operador la producción de {orden.codigo}"
                    else:
                        orden.estado = OrdenProduccion.Estado.CON_NOVEDAD
                        texto = f"detuvo la orden {orden.codigo} por novedad en producción"
                    orden.save(update_fields=["estado"])
                    registrar(request.user, "PRODUCCION", texto[:255], False, orden.codigo, f"{tipo}: {motivo}")
                messages.success(request, f"{orden.codigo} marcada con novedad. Quedó en el historial con su motivo.")
                return redirect("jefe_ordenes")
        else:
            errores.append("Elige Aprobar o Marcar con novedad.")

    return render(request, "jefe/revisar.html", {
        "orden": orden, "registro": registro, "valores": valores, "fuera": fuera, "menos": menos,
        "errores": errores, "datos": datos, "tipos": TIPOS_NOVEDAD,
        "duracion": registro.fin - registro.inicio,
        "novedad_abierta": bool(datos.get("accion") == "novedad"),
    })
