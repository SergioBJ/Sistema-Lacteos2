from django.contrib import admin

from .models import Cliente, Material, Producto, Proveedor, Tamano, TipoProducto


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "tipo", "unidad", "stock_minimo", "activo")
    list_filter = ("tipo", "activo")
    search_fields = ("codigo", "nombre")


class TamanoInline(admin.TabularInline):
    model = Tamano
    extra = 1


@admin.register(TipoProducto)
class TipoProductoAdmin(admin.ModelAdmin):
    search_fields = ("nombre",)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("tipo", "marca", "vida_util_meses", "activo")
    list_filter = ("tipo", "marca", "activo")
    inlines = [TamanoInline]


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nit", "nombre", "telefono", "activo")
    list_filter = ("activo", "materiales")
    search_fields = ("nit", "nombre")
    filter_horizontal = ("materiales",)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nit", "nombre", "ciudad", "activo")
    search_fields = ("nit", "nombre")
