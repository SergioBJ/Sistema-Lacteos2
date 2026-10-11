"""Pantalla genérica del Gerente: una tabla con la lista y, debajo, el formulario
para crear o editar. La usan Usuarios, Proveedores, Clientes y Materiales."""
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from inventario.historial import registrar


def lista_y_formulario(request, cfg, pk=None):
    modelo = cfg["modelo"]
    objeto = get_object_or_404(modelo, pk=pk) if pk else None
    clase_form = cfg.get("form_editar", cfg["form"]) if objeto else cfg["form"]

    if request.method == "POST":
        form = clase_form(request.POST, instance=objeto)
        if form.is_valid():
            with transaction.atomic():
                nuevo = form.save()
                verbo = "editó" if objeto else "creó"
                registrar(request.user, "ADMINISTRACION", f"{verbo} {cfg['que']} {cfg['nombre'](nuevo)}"[:255],
                          True, cfg["referencia"](nuevo)[:30])
            messages.success(request, f"Se guardó {cfg['que']} {cfg['nombre'](nuevo)}.")
            return redirect(reverse(cfg["ruta"]) + cfg.get("query", ""))
    else:
        form = clase_form(instance=objeto, initial=None if objeto else cfg.get("inicial"))

    lista = modelo.objects.filter(**cfg.get("filtro", {}))
    q = request.GET.get("q", "").strip()
    if q:
        filtro = Q()
        for campo in cfg["buscar_en"]:
            filtro |= Q(**{f"{campo}__icontains": q})
        lista = lista.filter(filtro)

    campo_activo = cfg.get("campo_activo", "activo")
    filas = [{
        "celdas": cfg["fila"](o),
        "activo": getattr(o, campo_activo),
        "editar": reverse(cfg["ruta"] + "_editar", args=[o.pk]),
        "estado": reverse(cfg["ruta"] + "_estado", args=[o.pk]),
        "es_actual": objeto is not None and o.pk == objeto.pk,
    } for o in lista]

    return render(request, cfg.get("plantilla", "gerente/lista_form.html"), {
        "cfg": cfg,
        "filas": filas,
        "form": form,
        "objeto": objeto,
        "q": q,
        "url_nuevo": reverse(cfg["ruta"]) + cfg.get("query", ""),
        **cfg.get("contexto", {}),
    })


@require_POST
def cambiar_estado(request, cfg, pk):
    modelo = cfg["modelo"]
    objeto = get_object_or_404(modelo, pk=pk)
    campo_activo = cfg.get("campo_activo", "activo")
    if cfg.get("puede_desactivar") and not cfg["puede_desactivar"](request, objeto):
        messages.error(request, "No puedes desactivar este registro.")
        return redirect(reverse(cfg["ruta"]) + cfg.get("query", ""))
    nuevo_estado = not getattr(objeto, campo_activo)
    with transaction.atomic():
        setattr(objeto, campo_activo, nuevo_estado)
        objeto.save(update_fields=[campo_activo])
        verbo = "activó" if nuevo_estado else "desactivó"
        registrar(request.user, "ADMINISTRACION", f"{verbo} {cfg['que']} {cfg['nombre'](objeto)}"[:255],
                  True, cfg["referencia"](objeto)[:30])
    messages.success(request, f"{cfg['que'].capitalize()} {cfg['nombre'](objeto)}: {'activo' if nuevo_estado else 'desactivado'}.")
    return redirect(reverse(cfg["ruta"]) + cfg.get("query", ""))
