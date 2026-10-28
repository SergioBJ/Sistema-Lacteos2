from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from catalogo.models import Material, TipoProducto
from inventario.historial import registrar
from usuarios.permisos import rol_requerido

from .models import Parametro


def _destino_desde(request):
    """Lee de la dirección si se está viendo un material (?material=) o un tipo de producto (?tipo=)."""
    if request.GET.get("material"):
        return "material", get_object_or_404(Material, pk=request.GET["material"])
    if request.GET.get("tipo"):
        return "tipo_producto", get_object_or_404(TipoProducto, pk=request.GET["tipo"])
    return None, None


def _txt(valor):
    """Número guardado -> texto con coma para mostrar en la casilla."""
    if valor is None:
        return ""
    return f"{valor.normalize():f}".replace(".", ",")


def _numero(texto):
    """Texto con coma o punto -> Decimal, o None si está vacío o no es número."""
    from decimal import Decimal, InvalidOperation
    t = (texto or "").strip().replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    try:
        n = Decimal(t)
    except InvalidOperation:
        return None
    if not n.is_finite() or abs(n) >= Decimal("1000000000"):
        return None
    return n.quantize(Decimal("0.001"))


def _fila(p, i):
    return {"i": i, "id": p.pk if p.pk else "", "nombre": p.nombre, "modo": p.modo,
            "min": _txt(p.minimo), "max": _txt(p.maximo), "unidad": p.unidad, "quitar": False, "error": ""}


def _leer_filas(post):
    filas = []
    for i in post.getlist("fila"):
        filas.append({
            "i": i, "id": post.get(f"id_{i}", "").strip(), "nombre": post.get(f"nombre_{i}", "").strip(),
            "modo": post.get(f"modo_{i}", ""), "min": post.get(f"min_{i}", "").strip(),
            "max": post.get(f"max_{i}", "").strip(), "unidad": post.get(f"unidad_{i}", "").strip(),
            "quitar": post.get(f"quitar_{i}") == "1", "error": "",
        })
    return filas


def _validar_fila(f):
    """Revisa una fila y devuelve (minimo, maximo, unidad) listos para guardar. Pone f['error'] si algo falla."""
    modo = f["modo"]
    if not f["nombre"]:
        f["error"] = "Escribe el nombre del parámetro."
        return None
    if len(f["nombre"]) > 100 or len(f["unidad"]) > 20:
        f["error"] = "El nombre (máx. 100 letras) o la unidad (máx. 20) son muy largos."
        return None
    if modo not in Parametro.MODOS:
        f["error"] = "Elige cómo se evalúa."
        return None
    if modo == Parametro.POSNEG:
        return None, 0, ""
    if modo == Parametro.CARACTERISTICO:
        return 1, None, ""
    minimo = _numero(f["min"]) if modo in (Parametro.MINIMO, Parametro.ENTRE) else None
    maximo = _numero(f["max"]) if modo in (Parametro.MAXIMO, Parametro.ENTRE) else None
    if modo in (Parametro.MINIMO, Parametro.ENTRE) and minimo is None:
        f["error"] = "Escribe un mínimo válido (solo números)."
        return None
    if modo in (Parametro.MAXIMO, Parametro.ENTRE) and maximo is None:
        f["error"] = "Escribe un máximo válido (solo números)."
        return None
    if modo == Parametro.ENTRE and minimo > maximo:
        f["error"] = "El mínimo no puede ser mayor que el máximo."
        return None
    return minimo, maximo, f["unidad"]


@rol_requerido("CALIDAD")
def parametros(request):
    campo, destino = _destino_desde(request)
    activos = Count("parametros", filter=Q(parametros__activo=True))
    materiales = list(Material.objects.filter(activo=True).annotate(n=activos).order_by("tipo", "nombre"))
    tipos = list(TipoProducto.objects.annotate(n=activos).order_by("nombre"))

    if destino is None:  # sin elegir: abre el primero que falte por llenar, o el primero de la lista
        primero = next((m for m in materiales if m.n == 0), None) or (materiales[0] if materiales else None)
        if primero is None:
            primero = next((t for t in tipos if t.n == 0), None) or (tipos[0] if tipos else None)
        if primero is not None:
            campo = "material" if isinstance(primero, Material) else "tipo_producto"
            destino = primero

    clave = "material" if campo == "material" else "tipo"
    filas, inactivos, copiado, errores, lista = [], [], None, False, []
    if destino is not None:
        filtro = {campo: destino}
        lista = list(Parametro.objects.filter(activo=True, **filtro).order_by("nombre"))
        inactivos = list(Parametro.objects.filter(activo=False, **filtro).order_by("nombre"))

        if request.method == "POST":
            filas = _leer_filas(request.POST)
            existentes = {str(p.pk): p for p in lista}
            nombres_inactivos = {p.nombre.lower(): p for p in inactivos}
            vistos = set()
            cambios = []  # (fila, parametro o None, minimo, maximo, unidad)
            for f in filas:
                actual = existentes.get(f["id"]) if f["id"] else None
                if f["id"] and actual is None:
                    f["error"] = "Este parámetro ya no existe. Recarga la página."
                    continue
                if f["quitar"]:
                    if actual is not None:
                        cambios.append((f, actual, None, None, None))
                    continue
                if actual is None and not (f["nombre"] or f["min"] or f["max"] or f["unidad"]):
                    continue  # fila nueva vacía: se ignora
                valores = _validar_fila(f)
                if valores is None:
                    continue
                nombre = f["nombre"].lower()
                if nombre in vistos:
                    f["error"] = "Este nombre está repetido en la lista."
                    continue
                if nombre in nombres_inactivos:
                    f["error"] = "Ya existe desactivado. Actívalo abajo en vez de crearlo otra vez."
                    continue
                vistos.add(nombre)
                cambios.append((f, actual, *valores))

            errores = any(f["error"] for f in filas)
            if not errores:
                agregados = editados = quitados = 0
                with transaction.atomic():
                    for f, p, minimo, maximo, unidad in cambios:
                        if f["quitar"]:
                            p.activo = False
                            p.save(update_fields=["activo"])
                            quitados += 1
                            continue
                        if p is None:
                            p = Parametro(**filtro)
                            agregados += 1
                        else:
                            antes = (p.nombre, p.metodo, p.minimo, p.maximo, p.unidad)
                        p.nombre, p.metodo, p.unidad = f["nombre"], f["modo"], unidad
                        p.minimo = None if minimo is None else _numero(str(minimo))
                        p.maximo = None if maximo is None else _numero(str(maximo))
                        if p.pk:
                            if antes == (p.nombre, p.metodo, p.minimo, p.maximo, p.unidad):
                                continue
                            editados += 1
                        p.save()
                    if agregados or editados or quitados:
                        partes = [t for t in (f"{agregados} agregados" if agregados else "",
                                              f"{editados} editados" if editados else "",
                                              f"{quitados} desactivados" if quitados else "") if t]
                        registrar(request.user, "ADMINISTRACION",
                                  f"actualizó los parámetros de {destino} ({', '.join(partes)})"[:255],
                                  True, getattr(destino, "codigo", "") or f"TP-{destino.pk}")
                if agregados or editados or quitados:
                    messages.success(request, f"Se guardaron los parámetros de {destino.nombre}.")
                else:
                    messages.success(request, "No había cambios por guardar.")
                return redirect(request.path + f"?{clave}={destino.pk}")
        else:
            filas = [_fila(p, n) for n, p in enumerate(lista)]
            origen = request.GET.get("copiar", "")
            if "-" in origen:
                tipo_origen, pk_origen = origen.split("-", 1)
                modelo = {"material": Material, "tipo": TipoProducto}.get(tipo_origen)
                fuente = modelo.objects.filter(pk=pk_origen).first() if modelo and pk_origen.isdigit() else None
                if fuente is not None and fuente != destino:
                    campo_fuente = "material" if modelo is Material else "tipo_producto"
                    ya = {f["nombre"].lower() for f in filas} | {p.nombre.lower() for p in inactivos}
                    nuevos = [p for p in Parametro.objects.filter(activo=True, **{campo_fuente: fuente}).order_by("nombre")
                              if p.nombre.lower() not in ya]
                    for p in nuevos:
                        fila = _fila(p, len(filas))
                        fila["id"] = ""
                        filas.append(fila)
                    copiado = (fuente.nombre, len(nuevos))
            if not filas:
                filas = [{"i": 0, "id": "", "nombre": "", "modo": Parametro.MAXIMO, "min": "", "max": "",
                          "unidad": "", "quitar": False, "error": ""}]

    grupos = []
    for tipo_valor, tipo_texto in Material.Tipo.choices:
        items = [m for m in materiales if m.tipo == tipo_valor]
        if items:
            grupos.append((tipo_texto, items))
    fuentes = ([("material", m) for m in materiales if m.n and not (campo == "material" and m == destino)]
               + [("tipo", t) for t in tipos if t.n and not (campo == "tipo_producto" and t == destino)])

    return render(request, "calidad/parametros.html", {
        "grupos": grupos,
        "tipos": tipos,
        "campo": campo,
        "destino": destino,
        "clave": clave,
        "filas": filas,
        "siguiente": max([int(f["i"]) for f in filas if str(f["i"]).isdigit()] + [-1]) + 1,
        "lista": lista,
        "vista_previa": lista[:2],
        "inactivos": inactivos,
        "fuentes": fuentes,
        "copiado": copiado,
        "errores": errores,
        "modos": Parametro.MODOS,
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
                             f"({p.rango_texto})")

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
                             f"({p.rango_texto})")
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
