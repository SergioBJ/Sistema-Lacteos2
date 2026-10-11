from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalogo.models import Material, TipoProducto
from inventario.historial import registrar
from usuarios.permisos import rol_requerido

from .forms import ParametroForm
from .models import Parametro


def _destino_desde(request):
    """Lee de la dirección si se está viendo un material (?material=) o un tipo de producto (?tipo=)."""
    if request.GET.get("material"):
        return "material", get_object_or_404(Material, pk=request.GET["material"])
    if request.GET.get("tipo"):
        return "tipo_producto", get_object_or_404(TipoProducto, pk=request.GET["tipo"])
    return None, None


@rol_requerido("CALIDAD")
def parametros(request):
    campo, destino = _destino_desde(request)
    activos = Count("parametros", filter=Q(parametros__activo=True))
    materiales = Material.objects.filter(activo=True).annotate(n=activos).order_by("tipo", "nombre")
    tipos = TipoProducto.objects.annotate(n=activos).order_by("nombre")

    form = None
    editando = None
    lista = []
    if destino is not None:
        filtro = {campo: destino}
        lista = Parametro.objects.filter(**filtro).order_by("-activo", "nombre")
        if request.GET.get("editar"):
            editando = get_object_or_404(Parametro, pk=request.GET["editar"], **filtro)

        if request.method == "POST":
            form = ParametroForm(request.POST, instance=editando, destino=filtro)
            if form.is_valid():
                with transaction.atomic():
                    p = form.save()
                    verbo = "editó" if editando else "agregó"
                    registrar(request.user, "ADMINISTRACION",
                              f"{verbo} el parámetro {p.nombre} de {destino}"[:255], True, f"PAR-{p.pk}")
                messages.success(request, f"Se guardó el parámetro {p.nombre} de {destino}.")
                return redirect(request.path + f"?{'material' if campo == 'material' else 'tipo'}={destino.pk}")
        else:
            form = ParametroForm(instance=editando, destino=filtro)

    sin_parametros = sum(1 for m in materiales if m.n == 0) + sum(1 for t in tipos if t.n == 0)
    grupos = []
    for tipo_valor, tipo_texto in Material.Tipo.choices:
        items = [m for m in materiales if m.tipo == tipo_valor]
        if items:
            grupos.append((tipo_texto, items))

    return render(request, "calidad/parametros.html", {
        "grupos": grupos,
        "tipos": tipos,
        "campo": campo,
        "destino": destino,
        "lista": lista,
        "form": form,
        "editando": editando,
        "sin_parametros": sin_parametros,
        "clave": "material" if campo == "material" else "tipo",
    })


@rol_requerido("CALIDAD")
@require_POST
def parametro_estado(request, pk):
    p = get_object_or_404(Parametro, pk=pk)
    with transaction.atomic():
        p.activo = not p.activo
        p.save(update_fields=["activo"])
        verbo = "activó" if p.activo else "desactivó"
        destino = p.material or p.tipo_producto
        registrar(request.user, "ADMINISTRACION", f"{verbo} el parámetro {p.nombre} de {destino}"[:255],
                  True, f"PAR-{p.pk}")
    messages.success(request, f"Parámetro {p.nombre}: {'activo' if p.activo else 'desactivado'}.")
    clave = f"material={p.material_id}" if p.material_id else f"tipo={p.tipo_producto_id}"
    return redirect(reverse("calidad_parametros") + "?" + clave)


# =====================================================================
# Mis tareas y Revisar material (etapa 2)
# =====================================================================
from decimal import Decimal, InvalidOperation  # noqa: E402

from django.urls import NoReverseMatch  # noqa: E402

from inventario.models import Llegada, LoteProducto  # noqa: E402

from .models import ResultadoRevision, RevisionMaterial  # noqa: E402


def _num(valor):
    """Convierte lo que escribe la persona (con coma o punto) en número. None si no es válido."""
    texto = (valor or "").strip().replace(" ", "")
    if not texto:
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _fmt(valor):
    if valor is None:
        return "—"
    return f"{valor.normalize():f}".replace(".", ",")


def _sin_parametros():
    activos = Count("parametros", filter=Q(parametros__activo=True))
    return (Material.objects.filter(activo=True).annotate(n=activos).filter(n=0).count()
            + TipoProducto.objects.annotate(n=activos).filter(n=0).count())


@rol_requerido("CALIDAD")
def tareas(request):
    try:
        url_liberacion = reverse("calidad_liberacion")
    except NoReverseMatch:
        url_liberacion = None
    pendientes = (Llegada.objects.filter(estado=Llegada.Estado.ESPERANDO)
                  .select_related("material", "proveedor", "registrado_por")
                  .annotate(n_par=Count("material__parametros", filter=Q(material__parametros__activo=True)))
                  .order_by("fecha"))
    return render(request, "calidad/tareas.html", {
        "pendientes": pendientes,
        "lotes": LoteProducto.objects.filter(estado=LoteProducto.Estado.POR_LIBERAR).select_related("tamano"),
        "sin_parametros": _sin_parametros(),
        "url_liberacion": url_liberacion,
    })


@rol_requerido("CALIDAD")
def revision_lista(request):
    return tareas(request)


@rol_requerido("CALIDAD")
def revision(request, pk):
    llegada = get_object_or_404(Llegada.objects.select_related("material", "proveedor", "registrado_por"), pk=pk)
    if llegada.estado != Llegada.Estado.ESPERANDO:
        messages.error(request, f"La llegada {llegada.codigo} ya fue revisada.")
        return redirect("calidad_tareas")

    parametros_ = list(Parametro.objects.filter(material=llegada.material, activo=True).order_by("nombre"))
    filas = []
    errores = []
    motivo_extra = ""

    if request.method == "POST" and parametros_:
        accion = request.POST.get("accion")
        motivo_extra = request.POST.get("motivo", "").strip()
        fuera = []
        for p in parametros_:
            valor = _num(request.POST.get(f"p_{p.pk}"))
            dentro = None if valor is None else p.en_rango(valor)
            filas.append({"p": p, "valor": request.POST.get(f"p_{p.pk}", ""), "num": valor, "dentro": dentro})
            if valor is None:
                errores.append(f"Falta el valor de {p.nombre}.")
            elif not dentro:
                fuera.append(f"{p.nombre} {_fmt(valor)}{(' ' + p.unidad) if p.unidad else ''} "
                             f"(rango {_fmt(p.minimo)} a {_fmt(p.maximo)})")

        if accion == "aprobar" and fuera:
            errores.append("Hay valores fuera del rango: no se puede aprobar. Solo se puede rechazar.")
        if accion == "rechazar" and not fuera and not motivo_extra:
            errores.append("Todo está en rango. Si igual la rechazas, escribe el motivo.")

        if not errores:
            aprobado = accion == "aprobar"
            motivo = ""
            if not aprobado:
                partes = []
                if fuera:
                    partes.append("Fuera de rango: " + "; ".join(fuera))
                if motivo_extra:
                    partes.append(motivo_extra)
                motivo = ". ".join(partes)
            with transaction.atomic():
                rev = RevisionMaterial.objects.create(
                    llegada=llegada, revisado_por=request.user, aprobado=aprobado, motivo=motivo)
                ResultadoRevision.objects.bulk_create([
                    ResultadoRevision(revision=rev, parametro=f["p"], valor=f["num"], dentro_rango=f["dentro"])
                    for f in filas
                ])
                llegada.estado = Llegada.Estado.APROBADA if aprobado else Llegada.Estado.RECHAZADA
                llegada.save(update_fields=["estado"])
                verbo = "aprobó" if aprobado else "rechazó"
                registrar(request.user, "REVISION",
                          f"{verbo} {llegada.material.nombre} lote {llegada.lote_proveedor} ({llegada.codigo})"[:255],
                          aprobado, llegada.lote_proveedor, motivo)
            if aprobado:
                messages.success(request, f"{llegada.material.nombre} lote {llegada.lote_proveedor} aprobado. Ya suma al inventario.")
            else:
                messages.success(request, f"{llegada.material.nombre} lote {llegada.lote_proveedor} rechazado. El motivo quedó en el historial.")
            return redirect("calidad_tareas")
    else:
        filas = [{"p": p, "valor": "", "num": None, "dentro": None} for p in parametros_]

    return render(request, "calidad/revision.html", {
        "llegada": llegada,
        "filas": filas,
        "errores": errores,
        "motivo": motivo_extra,
        "rangos": {str(f["p"].pk): [str(f["p"].minimo) if f["p"].minimo is not None else None,
                                    str(f["p"].maximo) if f["p"].maximo is not None else None] for f in filas},
    })


# =====================================================================
# Liberar lote (etapa 5)
# =====================================================================
from .models import Liberacion, ResultadoLiberacion  # noqa: E402


@rol_requerido("CALIDAD")
def liberacion_lista(request):
    lotes = (LoteProducto.objects.filter(estado=LoteProducto.Estado.POR_LIBERAR)
             .select_related("tamano__producto__tipo", "orden").order_by("fecha_produccion"))
    return render(request, "calidad/liberacion_lista.html", {"lotes": lotes})


@rol_requerido("CALIDAD")
def liberacion(request, pk):
    lote = get_object_or_404(LoteProducto.objects.select_related("tamano__producto__tipo", "orden__operador"), pk=pk)
    if lote.estado != LoteProducto.Estado.POR_LIBERAR:
        messages.error(request, f"El lote {lote.codigo} ya fue revisado.")
        return redirect("calidad_liberacion")
    tipo = lote.tamano.producto.tipo
    parametros_ = list(Parametro.objects.filter(tipo_producto=tipo, activo=True).order_by("nombre"))
    filas, errores, motivo_extra = [], [], ""

    if request.method == "POST" and parametros_:
        accion = request.POST.get("accion")
        motivo_extra = request.POST.get("motivo", "").strip()
        fuera = []
        for p in parametros_:
            valor = _num(request.POST.get(f"p_{p.pk}"))
            dentro = None if valor is None else p.en_rango(valor)
            filas.append({"p": p, "valor": request.POST.get(f"p_{p.pk}", ""), "num": valor, "dentro": dentro})
            if valor is None:
                errores.append(f"Falta el valor de {p.nombre}.")
            elif not dentro:
                fuera.append(f"{p.nombre} {_fmt(valor)}{(' ' + p.unidad) if p.unidad else ''} "
                             f"(rango {_fmt(p.minimo)} a {_fmt(p.maximo)})")
        if accion == "aprobar" and fuera:
            errores.append("Hay valores fuera del rango: no se puede liberar. Solo se puede marcar como no conforme.")
        if accion == "rechazar" and not fuera and not motivo_extra:
            errores.append("Todo está en rango. Si igual lo marcas no conforme, escribe el motivo.")

        if not errores:
            liberado = accion == "aprobar"
            motivo = ""
            if not liberado:
                partes = (["Fuera de rango: " + "; ".join(fuera)] if fuera else []) + ([motivo_extra] if motivo_extra else [])
                motivo = ". ".join(partes)
            with transaction.atomic():
                lib = Liberacion.objects.create(lote=lote, revisado_por=request.user, liberado=liberado, motivo=motivo)
                ResultadoLiberacion.objects.bulk_create([
                    ResultadoLiberacion(liberacion=lib, parametro=f["p"], valor=f["num"], dentro_rango=f["dentro"])
                    for f in filas
                ])
                lote.estado = LoteProducto.Estado.LIBERADO if liberado else LoteProducto.Estado.NO_CONFORME
                lote.save(update_fields=["estado"])
                texto = (f"liberó el lote {lote.codigo} ({lote.cantidad} × {lote.tamano})" if liberado
                         else f"marcó no conforme el lote {lote.codigo} ({lote.tamano})")
                registrar(request.user, "LIBERACION", texto[:255], liberado, lote.codigo, motivo)
            if liberado:
                messages.success(request, f"Lote {lote.codigo} liberado. El Almacenista ya lo puede guardar y despachar.")
            else:
                messages.success(request, f"Lote {lote.codigo} marcado no conforme. Quedó bloqueado y el motivo está en el historial.")
            return redirect("calidad_tareas")
    else:
        filas = [{"p": p, "valor": "", "num": None, "dentro": None} for p in parametros_]

    return render(request, "calidad/liberacion.html", {
        "lote": lote, "tipo": tipo, "filas": filas, "errores": errores, "motivo": motivo_extra,
        "rangos": {str(f["p"].pk): [str(f["p"].minimo) if f["p"].minimo is not None else None,
                                    str(f["p"].maximo) if f["p"].maximo is not None else None] for f in filas},
    })
