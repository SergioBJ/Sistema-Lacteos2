from django.contrib import admin

from .models import (
    FormulaEmpaque, FormulaLimpieza, FormulaMateria, OrdenProduccion,
    RegistroProduccion, RevisionJefe, ValorProceso,
)


@admin.register(FormulaMateria)
class FormulaMateriaAdmin(admin.ModelAdmin):
    list_display = ("producto", "material", "cantidad_por_kg")
    list_filter = ("producto",)


@admin.register(FormulaEmpaque)
class FormulaEmpaqueAdmin(admin.ModelAdmin):
    list_display = ("tamano", "material", "cantidad_por_unidad")


@admin.register(FormulaLimpieza)
class FormulaLimpiezaAdmin(admin.ModelAdmin):
    list_display = ("producto", "material", "cantidad_por_orden")


@admin.register(OrdenProduccion)
class OrdenProduccionAdmin(admin.ModelAdmin):
    list_display = ("codigo", "tamano", "cantidad", "cliente", "operador", "estado", "fecha")
    list_filter = ("estado",)
    search_fields = ("codigo",)


class ValorProcesoInline(admin.TabularInline):
    model = ValorProceso
    extra = 0


@admin.register(RegistroProduccion)
class RegistroProduccionAdmin(admin.ModelAdmin):
    list_display = ("orden", "operador", "cantidad_producida", "limpieza_hecha", "fecha")
    inlines = [ValorProcesoInline]


@admin.register(RevisionJefe)
class RevisionJefeAdmin(admin.ModelAdmin):
    list_display = ("registro", "aprobado", "tipo_novedad", "accion", "fecha")
