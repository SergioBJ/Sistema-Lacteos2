"""Lo que hace el Supervisor de Calidad: parámetros, revisión de materiales y liberación de lotes."""
from django.conf import settings
from django.db import models
from django.db.models import Q


class Parametro(models.Model):
    """Un parámetro con su rango. Es de un material o de un tipo de producto, nunca de los dos."""

    material = models.ForeignKey(
        "catalogo.Material", on_delete=models.PROTECT, null=True, blank=True, related_name="parametros"
    )
    tipo_producto = models.ForeignKey(
        "catalogo.TipoProducto", on_delete=models.PROTECT, null=True, blank=True, related_name="parametros"
    )
    nombre = models.CharField(max_length=100)  # Acidez, Grasa, Antibióticos...
    metodo = models.CharField("cómo se evalúa", max_length=150, blank=True)
    minimo = models.DecimalField("mínimo", max_digits=12, decimal_places=3, null=True, blank=True)
    maximo = models.DecimalField("máximo", max_digits=12, decimal_places=3, null=True, blank=True)
    unidad = models.CharField(max_length=20, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["material", "tipo_producto", "nombre"]
        verbose_name = "parámetro"
        constraints = [
            models.CheckConstraint(
                condition=(Q(material__isnull=False, tipo_producto__isnull=True)
                           | Q(material__isnull=True, tipo_producto__isnull=False)),
                name="parametro_de_material_o_producto",
            ),
        ]

    def __str__(self):
        return f"{self.material or self.tipo_producto} · {self.nombre}"

    def en_rango(self, valor):
        if self.minimo is not None and valor < self.minimo:
            return False
        if self.maximo is not None and valor > self.maximo:
            return False
        return True


class RevisionMaterial(models.Model):
    """Etapa 2: Calidad revisa un material que llegó."""

    llegada = models.OneToOneField("inventario.Llegada", on_delete=models.PROTECT, related_name="revision")
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    aprobado = models.BooleanField()
    motivo = models.TextField(blank=True, help_text="Obligatorio si se rechaza.")

    class Meta:
        verbose_name = "revisión de material"
        verbose_name_plural = "revisiones de material"

    def __str__(self):
        return f"Revisión {self.llegada}"


class ResultadoRevision(models.Model):
    revision = models.ForeignKey(RevisionMaterial, on_delete=models.PROTECT, related_name="resultados")
    parametro = models.ForeignKey(Parametro, on_delete=models.PROTECT)
    valor = models.DecimalField(max_digits=12, decimal_places=3)
    dentro_rango = models.BooleanField()

    class Meta:
        verbose_name = "resultado de revisión"
        verbose_name_plural = "resultados de revisión"


class Liberacion(models.Model):
    """Etapa 5: Calidad libera un lote de producto terminado o lo marca no conforme."""

    lote = models.OneToOneField("inventario.LoteProducto", on_delete=models.PROTECT, related_name="liberacion")
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    liberado = models.BooleanField()
    motivo = models.TextField(blank=True, help_text="Obligatorio si no es conforme.")

    class Meta:
        verbose_name = "liberación"
        verbose_name_plural = "liberaciones"

    def __str__(self):
        return f"Liberación {self.lote}"


class ResultadoLiberacion(models.Model):
    liberacion = models.ForeignKey(Liberacion, on_delete=models.PROTECT, related_name="resultados")
    parametro = models.ForeignKey(Parametro, on_delete=models.PROTECT)
    valor = models.DecimalField(max_digits=12, decimal_places=3)
    dentro_rango = models.BooleanField()

    class Meta:
        verbose_name = "resultado de liberación"
        verbose_name_plural = "resultados de liberación"
