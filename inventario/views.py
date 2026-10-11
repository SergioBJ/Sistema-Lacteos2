from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from catalogo.models import Material
from produccion.models import OrdenProduccion
from usuarios.permisos import rol_requerido

from .forms import LlegadaForm
from .historial import registrar
from .models import Llegada, LoteProducto


def _url_o_nada(nombre):
    try:
        return reverse(nombre)
    except NoReverseMatch:
        return None


def siguiente_codigo_llegada():
    anio = timezone.localdate().year
    prefijo = f"ING-{anio}-"
    n = Llegada.objects.filter(codigo__startswith=prefijo).count() + 1
    while Llegada.objects.filter(codigo=f"{prefijo}{n:04d}").exists():
        n += 1
    return f"{prefijo}{n:04d}"


def _cantidad(valor, material):
    texto = f"{valor:,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{texto} {material.unidad}"


@rol_requerido("ALMACENISTA")
def tareas(request):
    hoy = timezone.localdate()
    return render(request, "almacen/tareas.html", {
        "ordenes_esperando": OrdenProduccion.objects.filter(
            estado=OrdenProduccion.Estado.ESPERANDO_MATERIALES).count(),
        "lotes_liberados": LoteProducto.objects.filter(
            estado__in=[LoteProducto.Estado.LIBERADO, LoteProducto.Estado.DESPACHADO_PARCIAL]).count(),
        "url_entrega": _url_o_nada("almacen_entrega"),
        "url_despacho": _url_o_nada("almacen_despacho"),
        "hoy": Llegada.objects.filter(registrado_por=request.user, fecha__date=hoy)
                              .select_related("material", "proveedor"),
    })


@rol_requerido("ALMACENISTA")
def recepcion(request):
    if request.method == "POST":
        form = LlegadaForm(request.POST)
        devolver = "devolver" in request.POST

        if devolver:
            # Para devolver, el material sigue siendo inválido para guardar en inventario
            # (por ejemplo, vencido), pero el motivo es obligatorio.
            motivo = request.POST.get("observaciones", "").strip()
            form.is_valid()
            errores_bloqueantes = [c for c in form.errors if c not in ("vencimiento", "__all__")]
            if not motivo:
                form.add_error("observaciones", "Para devolver, escribe por qué se devuelve.")
            elif not errores_bloqueantes:
                d = form.cleaned_data
                try:
                    vence = form.fields["vencimiento"].clean(request.POST.get("vencimiento"))
                except Exception:
                    vence = None
                with transaction.atomic():
                    llegada = Llegada(
                        codigo=siguiente_codigo_llegada(),
                        material=d["material"], proveedor=d["proveedor"],
                        lote_proveedor=d["lote_proveedor"], cantidad=d["cantidad"],
                        vencimiento=vence or timezone.localdate(),
                        ficha_tecnica=d.get("ficha_tecnica", False), certificado=d.get("certificado", False),
                        remision=d.get("remision", False), observaciones=motivo,
                        estado=Llegada.Estado.DEVUELTA, registrado_por=request.user,
                    )
                    llegada.save()
                    registrar(request.user, "RECEPCION",
                              f"devolvió al proveedor {_cantidad(llegada.cantidad, llegada.material)} de "
                              f"{llegada.material.nombre} (lote {llegada.lote_proveedor})"[:255],
                              False, llegada.lote_proveedor, motivo)
                messages.success(request, f"Quedó registrada la devolución {llegada.codigo}.")
                return redirect("almacen_tareas")
        elif form.is_valid():
            with transaction.atomic():
                llegada = form.save(commit=False)
                llegada.codigo = siguiente_codigo_llegada()
                llegada.registrado_por = request.user
                llegada.save()
                registrar(request.user, "RECEPCION",
                          f"registró la llegada de {_cantidad(llegada.cantidad, llegada.material)} de "
                          f"{llegada.material.nombre} (lote {llegada.lote_proveedor})"[:255],
                          True, llegada.lote_proveedor)
            messages.success(request, f"Llegada {llegada.codigo} guardada. Quedó esperando la revisión de Calidad.")
            return redirect("almacen_tareas")
    else:
        form = LlegadaForm()

    # Datos para que la pantalla filtre materiales y proveedores sin recargar.
    materiales = Material.objects.filter(activo=True).prefetch_related("proveedores")
    datos = {
        str(m.pk): {
            "tipo": m.tipo,
            "unidad": m.get_unidad_display(),
            "proveedores": [p.pk for p in m.proveedores.all() if p.activo],
        }
        for m in materiales
    }
    return render(request, "almacen/recepcion.html", {
        "form": form,
        "datos_materiales": datos,
        "proximo_codigo": siguiente_codigo_llegada(),
    })


# =====================================================================
# Entregar a producción (etapa 3)
# =====================================================================
from decimal import Decimal  # noqa: E402

from django.shortcuts import get_object_or_404  # noqa: E402

from produccion.calculo import necesidades  # noqa: E402

from .models import Entrega, EntregaDetalle  # noqa: E402
from .stock import repartir_en_lotes  # noqa: E402


def _plan_entrega(orden):
    """Para cada material de la orden: cuánto necesita, de qué lotes sale y si falta."""
    filas = []
    for material, cant in sorted(necesidades(orden.tamano, orden.cantidad).items(),
                                 key=lambda x: (x[0].tipo, x[0].nombre)):
        cant = cant.quantize(Decimal("0.01"))
        plan, falta = repartir_en_lotes(material, cant)
        filas.append({"material": material, "necesita": cant, "plan": plan, "falta": falta.quantize(Decimal("0.01"))})
    return filas


@rol_requerido("ALMACENISTA")
def entregas(request):
    pendientes = (OrdenProduccion.objects.filter(estado=OrdenProduccion.Estado.ESPERANDO_MATERIALES)
                  .select_related("tamano__producto__tipo", "operador", "cliente").order_by("fecha"))
    return render(request, "almacen/entregas.html", {"pendientes": pendientes})


@rol_requerido("ALMACENISTA")
def entrega_orden(request, pk):
    orden = get_object_or_404(OrdenProduccion.objects.select_related("tamano__producto__tipo", "operador"), pk=pk)
    if orden.estado != OrdenProduccion.Estado.ESPERANDO_MATERIALES:
        messages.error(request, f"La orden {orden.codigo} no está esperando materiales.")
        return redirect("almacen_entrega")

    filas = _plan_entrega(orden)
    faltantes = [f for f in filas if f["falta"] > 0]

    if request.method == "POST":
        with transaction.atomic():
            # Se vuelve a calcular dentro de la transacción por si alguien entregó algo mientras tanto.
            filas = _plan_entrega(orden)
            faltantes = [f for f in filas if f["falta"] > 0]
            if faltantes:
                motivo = "; ".join(f"Falta {f['material'].nombre} ({f['falta']:g} {f['material'].unidad})" for f in faltantes)
                orden.estado = OrdenProduccion.Estado.DETENIDA
                orden.motivo_detenida = motivo
                orden.save(update_fields=["estado", "motivo_detenida"])
                registrar(request.user, "ORDEN", f"no pudo entregar los materiales de {orden.codigo}", False,
                          orden.codigo, motivo)
                messages.error(request, f"No alcanzó el material. La orden {orden.codigo} quedó detenida: {motivo}.")
                return redirect("almacen_entrega")

            entrega = Entrega.objects.create(orden=orden, entregado_por=request.user)
            EntregaDetalle.objects.bulk_create([
                EntregaDetalle(entrega=entrega, llegada=llegada, cantidad=cantidad)
                for f in filas for llegada, cantidad in f["plan"]
            ])
            orden.estado = OrdenProduccion.Estado.EN_PRODUCCION
            orden.save(update_fields=["estado"])
            registrar(request.user, "ORDEN",
                      f"entregó los materiales de {orden.codigo} ({len(filas)} materiales) a "
                      f"{orden.operador.get_full_name() or orden.operador.username}"[:255],
                      True, orden.codigo)
        messages.success(request, f"Materiales de {orden.codigo} entregados. Se descontaron del inventario y el operador ya puede empezar.")
        return redirect("almacen_entrega")

    return render(request, "almacen/entrega_orden.html", {"orden": orden, "filas": filas, "faltantes": faltantes})


# =====================================================================
# Bodega y despacho
# =====================================================================
from django.db.models import Sum  # noqa: E402

from catalogo.models import Cliente  # noqa: E402

from .models import Despacho  # noqa: E402


def saldo_lote(lote):
    despachado = lote.despachos.aggregate(t=Sum("cantidad"))["t"] or 0
    return lote.cantidad - despachado


@rol_requerido("ALMACENISTA")
def despachos(request):
    E = LoteProducto.Estado
    lotes = (LoteProducto.objects.filter(estado__in=[E.LIBERADO, E.DESPACHADO_PARCIAL])
             .select_related("tamano__producto__tipo", "orden__cliente").order_by("vencimiento"))
    for lote in lotes:
        lote.saldo = saldo_lote(lote)
    hoy = timezone.localdate()
    return render(request, "almacen/despachos.html", {
        "lotes": lotes,
        "bloqueados": LoteProducto.objects.filter(estado=E.NO_CONFORME).select_related("tamano")[:20],
        "recientes": Despacho.objects.select_related("lote__tamano", "cliente").filter(fecha__date__gte=hoy.replace(day=1))[:15],
        "hoy": hoy,
    })


@rol_requerido("ALMACENISTA")
def despacho_lote(request, pk):
    E = LoteProducto.Estado
    lote = get_object_or_404(LoteProducto.objects.select_related("tamano__producto__tipo", "orden__cliente"), pk=pk)
    if lote.estado not in (E.LIBERADO, E.DESPACHADO_PARCIAL):
        messages.error(request, f"El lote {lote.codigo} no está liberado por Calidad: no se puede despachar.")
        return redirect("almacen_despacho")
    saldo = saldo_lote(lote)
    errores, datos = [], {}

    if request.method == "POST":
        datos = request.POST
        if datos.get("accion") == "ubicar":
            ubicacion = datos.get("ubicacion", "").strip()
            if not ubicacion:
                errores.append("Escribe dónde queda guardado el lote (por ejemplo, Estante B-3).")
            else:
                with transaction.atomic():
                    lote.ubicacion = ubicacion[:40]
                    lote.save(update_fields=["ubicacion"])
                    registrar(request.user, "DESPACHO", f"guardó el lote {lote.codigo} en {lote.ubicacion}",
                              True, lote.codigo)
                messages.success(request, f"Lote {lote.codigo} guardado en {lote.ubicacion}.")
                return redirect("almacen_despacho")
        else:
            cliente = Cliente.objects.filter(pk=datos.get("cliente") or 0, activo=True).first()
            try:
                cantidad = int(datos.get("cantidad", ""))
            except ValueError:
                cantidad = 0
            factura = datos.get("factura", "").strip()
            if not cliente:
                errores.append("Elige el cliente.")
            if cantidad <= 0:
                errores.append("Escribe cuántas unidades salen.")
            elif cantidad > saldo:
                errores.append(f"Solo quedan {saldo} unidades en este lote.")
            if not factura:
                errores.append("Escribe el número de factura o remisión.")
            if lote.vencimiento < timezone.localdate():
                errores.append("Este lote ya está vencido: no se puede despachar.")
            if not errores:
                with transaction.atomic():
                    Despacho.objects.create(
                        lote=lote, cliente=cliente, cantidad=cantidad, factura=factura[:30],
                        vehiculo=datos.get("vehiculo", "").strip()[:15], conductor=datos.get("conductor", "").strip()[:100],
                        despachado_por=request.user,
                    )
                    nuevo_saldo = saldo - cantidad
                    lote.estado = E.DESPACHADO if nuevo_saldo == 0 else E.DESPACHADO_PARCIAL
                    lote.save(update_fields=["estado"])
                    registrar(request.user, "DESPACHO",
                              f"despachó {cantidad} × {lote.tamano} a {cliente} (lote {lote.codigo}, factura {factura})"[:255],
                              True, lote.codigo)
                messages.success(request, f"Despacho registrado: {cantidad} unidades a {cliente}. Quedan {nuevo_saldo} en el lote.")
                return redirect("almacen_despacho")

    return render(request, "almacen/despacho_lote.html", {
        "lote": lote, "saldo": saldo, "errores": errores, "datos": datos,
        "clientes": Cliente.objects.filter(activo=True),
        "cliente_orden": lote.orden.cliente_id,
    })
