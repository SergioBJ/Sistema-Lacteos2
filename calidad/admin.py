from django.contrib import admin

from .models import Liberacion, Parametro, ResultadoLiberacion, ResultadoRevision, RevisionMaterial


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ("nombre", "material", "tipo_producto", "minimo", "maximo", "unidad", "activo")
    list_filter = ("material", "tipo_producto", "activo")


class ResultadoRevisionInline(admin.TabularInline):
    model = ResultadoRevision
    extra = 0


@admin.register(RevisionMaterial)
class RevisionMaterialAdmin(admin.ModelAdmin):
    list_display = ("llegada", "aprobado", "revisado_por", "fecha")
    inlines = [ResultadoRevisionInline]


class ResultadoLiberacionInline(admin.TabularInline):
    model = ResultadoLiberacion
    extra = 0


@admin.register(Liberacion)
class LiberacionAdmin(admin.ModelAdmin):
    list_display = ("lote", "liberado", "revisado_por", "fecha")
    inlines = [ResultadoLiberacionInline]
