"""Lo que hacen el Jefe de Producción y el Operador: fórmulas, órdenes, registro y revisión."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class FormulaMateria(models.Model):
    """Materia prima que lleva cada 1 kg (o 1 L) de un producto. Sirve para todos sus tamaños."""

    producto = models.ForeignKey("catalogo.Producto", on_delete=models.PROTECT, related_name="formula_materias")
    material = models.ForeignKey("catalogo.Material", on_delete=models.PROTECT)
    cantidad_por_kg = models.DecimalField(
        "cantidad por kg", max_digits=12, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )

    class Meta:
        verbose_name = "fórmula · materia prima"
        verbose_name_plural = "fórmulas · materias primas"
        constraints = [models.UniqueConstraint(fields=["producto", "material"], name="formula_materia_unica")]


class FormulaEmpaque(models.Model):
    """Empaque que lleva cada unidad de un tamaño (saco 25 kg → 1 saco + 1 bolsa interna)."""

    tamano = models.ForeignKey("catalogo.Tamano", on_delete=models.PROTECT, related_name="formula_empaques")
    material = models.ForeignKey("catalogo.Material", on_delete=models.PROTECT)
    cantidad_por_unidad = models.DecimalField(
        "cantidad por unidad", max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))]
    )

    class Meta:
        verbose_name = "fórmula · empaque"
        verbose_name_plural = "fórmulas · empaques"
        constraints = [models.UniqueConstraint(fields=["tamano", "material"], name="formula_empaque_unica")]


class FormulaLimpieza(models.Model):
    """Desinfectante fijo que se usa en cada orden de un producto."""

    producto = models.ForeignKey("catalogo.Producto", on_delete=models.PROTECT, related_name="formula_limpieza")
    material = models.ForeignKey("catalogo.Material", on_delete=models.PROTECT)
    cantidad_por_orden = models.DecimalField(
        "cantidad por orden", max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))]
    )

    class Meta:
        verbose_name = "fórmula · limpieza"
        verbose_name_plural = "fórmulas · limpieza"
        constraints = [models.UniqueConstraint(fields=["producto", "material"], name="formula_limpieza_unica")]


class OrdenProduccion(models.Model):
    """Etapa 3: el Jefe crea la orden."""

    class Estado(models.TextChoices):
        ESPERANDO_MATERIALES = "ESPERANDO_MATERIALES", "Esperando materiales"
        DETENIDA = "DETENIDA", "Detenida"
        EN_PRODUCCION = "EN_PRODUCCION", "En producción"
        POR_REVISAR = "POR_REVISAR", "Por revisar"
        CON_NOVEDAD = "CON_NOVEDAD", "Con novedad"
        APROBADA = "APROBADA", "Aprobada"

    codigo = models.CharField("código", max_length=20, unique=True)  # OP-2026-014
    tamano = models.ForeignKey("catalogo.Tamano", on_delete=models.PROTECT, verbose_name="producto y tamaño")
    cantidad = models.PositiveIntegerField("cantidad (unidades)", validators=[MinValueValidator(1)])
    cliente = models.ForeignKey("catalogo.Cliente", on_delete=models.PROTECT, null=True, blank=True)
    operador = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ordenes_asignadas",
        limit_choices_to={"rol": "OPERADOR"},
    )
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ordenes_creadas")
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=25, choices=Estado.choices, default=Estado.ESPERANDO_MATERIALES)
    motivo_detenida = models.TextField("motivo si se detiene", blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "orden de producción"
        verbose_name_plural = "órdenes de producción"

    def __str__(self):
        return f"{self.codigo} · {self.cantidad} × {self.tamano}"


class RegistroProduccion(models.Model):
    """Etapa 4: el Operador registra lo que produjo."""

    orden = models.OneToOneField(OrdenProduccion, on_delete=models.PROTECT, related_name="registro")
    operador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    limpieza_hecha = models.BooleanField("limpieza hecha", default=False)
    cantidad_producida = models.PositiveIntegerField("cantidad producida (unidades)")
    novedades = models.TextField(blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "registro de producción"
        verbose_name_plural = "registros de producción"

    def __str__(self):
        return f"Registro {self.orden.codigo}"


class ValorProceso(models.Model):
    """Un parámetro del proceso medido por el Operador (temperatura, tiempo...)."""

    registro = models.ForeignKey(RegistroProduccion, on_delete=models.PROTECT, related_name="valores")
    nombre = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=12, decimal_places=3)
    minimo = models.DecimalField("mínimo", max_digits=12, decimal_places=3, null=True, blank=True)
    maximo = models.DecimalField("máximo", max_digits=12, decimal_places=3, null=True, blank=True)
    unidad = models.CharField(max_length=20, blank=True)
    dentro_rango = models.BooleanField()

    class Meta:
        verbose_name = "valor del proceso"
        verbose_name_plural = "valores del proceso"


class RevisionJefe(models.Model):
    """Etapa 4: el Jefe aprueba la producción o la marca con novedad."""

    class Accion(models.TextChoices):
        DEVOLVER = "DEVOLVER", "Devolver al operador"
        DETENER = "DETENER", "Detener la orden"

    registro = models.ForeignKey(RegistroProduccion, on_delete=models.PROTECT, related_name="revisiones")
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)
    aprobado = models.BooleanField()
    tipo_novedad = models.CharField("tipo de novedad", max_length=80, blank=True)
    motivo = models.TextField("por qué no pasó", blank=True)
    accion = models.CharField("qué se hace", max_length=10, choices=Accion.choices, blank=True)

    class Meta:
        verbose_name = "revisión del jefe"
        verbose_name_plural = "revisiones del jefe"
