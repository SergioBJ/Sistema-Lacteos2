from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from inventario.historial import registrar
from usuarios.permisos import rol_requerido

from .forms import ClienteForm, MaterialForm, ProductoForm, ProveedorForm, tamanos_formset
from .models import Cliente, Material, Producto, Proveedor, Tamano, TipoProducto
from .vistas_base import cambiar_estado, lista_y_formulario


def _chips(textos):
    return format_html_join("", '<span class="pill ne" style="margin: 2px 4px 2px 0">{}</span>', ((t,) for t in textos)) or "—"


# ---------------- Proveedores ----------------
PROVEEDORES = {
    "modelo": Proveedor,
    "form": ProveedorForm,
    "ruta": "gerente_proveedores",
    "titulo": "Proveedores",
    "sub": "La lista que usa el Almacenista al registrar una llegada. Marca qué materiales suministra cada uno.",
    "que": "el proveedor",
    "nuevo": "Nuevo proveedor",
    "cabeceras": ["NIT", "Nombre", "Qué suministra", "Teléfono"],
    "fila": lambda p: [p.nit, p.nombre, _chips(m.nombre for m in p.materiales.all()), p.telefono or "—"],
    "nombre": lambda p: p.nombre,
    "referencia": lambda p: p.nit,
    "buscar_en": ["nit", "nombre"],
}


@rol_requerido("GERENTE")
def proveedores(request, pk=None):
    return lista_y_formulario(request, PROVEEDORES, pk)


@rol_requerido("GERENTE")
def proveedor_estado(request, pk):
    return cambiar_estado(request, PROVEEDORES, pk)


# ---------------- Clientes ----------------
CLIENTES = {
    "modelo": Cliente,
    "form": ClienteForm,
    "ruta": "gerente_clientes",
    "titulo": "Clientes",
    "sub": "La lista que usan el Jefe en las órdenes y el Almacenista en los despachos. Solo NIT y nombre son obligatorios.",
    "que": "el cliente",
    "nuevo": "Nuevo cliente",
    "cabeceras": ["NIT", "Nombre", "Ciudad", "Teléfono"],
    "fila": lambda c: [c.nit, c.nombre, c.ciudad or "—", c.telefono or "—"],
    "nombre": lambda c: c.nombre,
    "referencia": lambda c: c.nit,
    "buscar_en": ["nit", "nombre", "ciudad"],
}


@rol_requerido("GERENTE")
def clientes(request, pk=None):
    return lista_y_formulario(request, CLIENTES, pk)


@rol_requerido("GERENTE")
def cliente_estado(request, pk):
    return cambiar_estado(request, CLIENTES, pk)


# ---------------- Materiales (con pestañas por tipo) ----------------
NOMBRES_PESTANA = {
    Material.Tipo.MATERIA_PRIMA: "Materia prima",
    Material.Tipo.EMPAQUE: "Insumos de empaque",
    Material.Tipo.DESINFECTANTE: "Desinfectantes",
}

MATERIALES = {
    "modelo": Material,
    "form": MaterialForm,
    "ruta": "gerente_materiales",
    "titulo": "Materiales y productos",
    "sub": "Todo lo que se puede registrar en el inventario. El tipo viene fijo en el programa.",
    "que": "el material",
    "nuevo": "Nuevo material",
    "cabeceras": ["Código", "Descripción", "Unidad", "Stock mínimo"],
    "fila": lambda m: [format_html('<span class="mono">{}</span>', m.codigo), format_html("<b>{}</b>", m.nombre),
                       m.get_unidad_display().capitalize(), f"{m.stock_minimo:,.0f}".replace(",", ".")
                       if m.stock_minimo == int(m.stock_minimo) else f"{m.stock_minimo:g}".replace(".", ",")],
    "nombre": lambda m: m.nombre,
    "referencia": lambda m: m.codigo,
    "buscar_en": ["codigo", "nombre"],
    "buscar_texto": "Buscar por código o descripción",
}


def pestanas_materiales(actual):
    """Las 4 pestañas de arriba con su cantidad."""
    conteos = {t: Material.objects.filter(tipo=t).count() for t in NOMBRES_PESTANA}
    lista = [{"nombre": NOMBRES_PESTANA[t], "n": conteos[t], "url": f"{reverse('gerente_materiales')}?tipo={t}",
              "on": actual == t} for t in NOMBRES_PESTANA]
    lista.append({"nombre": "Producto terminado", "n": Tamano.objects.filter(producto__activo=True).count(),
                  "url": reverse("gerente_materiales_productos"), "on": actual == "PRODUCTO"})
    return lista


def _cfg_materiales(tipo):
    return {**MATERIALES, "filtro": {"tipo": tipo}, "inicial": {"tipo": tipo}, "query": f"?tipo={tipo}",
            "contexto": {"pestanas": pestanas_materiales(tipo), "tipo_actual": tipo}}


def _tipo_pedido(request, objeto=None):
    if objeto is not None:
        return objeto.tipo
    tipo = request.GET.get("tipo") or request.POST.get("tipo")
    return tipo if tipo in NOMBRES_PESTANA else Material.Tipo.MATERIA_PRIMA


@rol_requerido("GERENTE")
def materiales(request, pk=None):
    objeto = get_object_or_404(Material, pk=pk) if pk else None
    return lista_y_formulario(request, _cfg_materiales(_tipo_pedido(request, objeto)), pk)


@rol_requerido("GERENTE")
def material_estado(request, pk):
    return cambiar_estado(request, _cfg_materiales(get_object_or_404(Material, pk=pk).tipo), pk)


# ---------------- Productos terminados (con sus tamaños) ----------------
@rol_requerido("GERENTE")
def productos(request, pk=None):
    producto = get_object_or_404(Producto, pk=pk) if pk else None
    FormSet = tamanos_formset(extra=0)

    if request.method == "POST":
        form = ProductoForm(request.POST, instance=producto)
        formset = FormSet(request.POST, instance=producto or Producto(), prefix="tamanos")
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                guardado = form.save()
                formset.instance = guardado
                formset.save()
                verbo = "editó" if producto else "creó"
                registrar(request.user, "ADMINISTRACION", f"{verbo} el producto {guardado}"[:255], True,
                          f"PROD-{guardado.pk}")
            messages.success(request, f"Se guardó el producto {guardado}.")
            return redirect("gerente_materiales_productos")
    else:
        form = ProductoForm(instance=producto)
        formset = FormSet(instance=producto or Producto(), prefix="tamanos")

    lista = Producto.objects.select_related("tipo").prefetch_related("tamanos")
    return render(request, "gerente/productos.html", {
        "form": form,
        "formset": formset,
        "producto": producto,
        "lista": lista,
        "tipos": TipoProducto.objects.all(),
        "pestanas": pestanas_materiales("PRODUCTO"),
        "total_tamanos": sum(p.tamanos.count() for p in lista),
    })


@rol_requerido("GERENTE")
def producto_estado(request, pk):
    if request.method != "POST":
        return redirect("gerente_materiales_productos")
    producto = get_object_or_404(Producto, pk=pk)
    with transaction.atomic():
        producto.activo = not producto.activo
        producto.save(update_fields=["activo"])
        verbo = "activó" if producto.activo else "desactivó"
        registrar(request.user, "ADMINISTRACION", f"{verbo} el producto {producto}"[:255], True, f"PROD-{producto.pk}")
    messages.success(request, f"Producto {producto}: {'activo' if producto.activo else 'desactivado'}.")
    return redirect("gerente_materiales_productos")
