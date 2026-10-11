from django.contrib import admin

from .models import Despacho, Entrega, EntregaDetalle, Llegada, LoteProducto, Movimiento


@admin.register(Llegada)
class LlegadaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "material", "proveedor", "lote_proveedor", "cantidad", "vencimiento", "estado")
    list_filter = ("estado", "material__tipo")
    search_fields = ("codigo", "lote_proveedor")


class EntregaDetalleInline(admin.TabularInline):
    model = EntregaDetalle
    extra = 0


@admin.register(Entrega)
class EntregaAdmin(admin.ModelAdmin):
    list_display = ("orden", "entregado_por", "fecha")
    inlines = [EntregaDetalleInline]


@admin.register(LoteProducto)
class LoteProductoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "tamano", "cantidad", "vencimiento", "estado", "ubicacion")
    list_filter = ("estado",)
    search_fields = ("codigo",)


@admin.register(Despacho)
class DespachoAdmin(admin.ModelAdmin):
    list_display = ("lote", "cliente", "cantidad", "factura", "fecha")
    list_filter = ("cliente",)


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    """El historial se puede consultar, pero nadie lo agrega, edita ni borra a mano."""

    list_display = ("fecha", "usuario", "etapa", "accion", "paso", "referencia")
    list_filter = ("etapa", "paso")
    search_fields = ("accion", "referencia", "motivo")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
