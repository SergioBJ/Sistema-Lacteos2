"""Lo que pasa por bodega: llegadas, entregas a producción, lotes, despachos e historial."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Llegada(models.Model):
    """Etapa 1: el Almacenista registra lo que llegó del proveedor."""

    class Estado(models.TextChoices):
        ESPERANDO = "ESPERANDO", "Esperando a Calidad"
        APROBADA = "APROBADA", "Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        DEVUELTA = "DEVUELTA", "Devuelta al proveedor"

    codigo = models.CharField("código", max_length=20, unique=True)  # ING-2026-0031
    material = models.ForeignKey("catalogo.Material", on_delete=models.PROTECT)
    proveedor = models.ForeignKey("catalogo.Proveedor", on_delete=models.PROTECT)
    lote_proveedor = models.CharField("lote del proveedor", max_length=50)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    vencimiento = models.DateField("fecha de vencimiento")
    ficha_tecnica = models.BooleanField("ficha técnica", default=False)
    certificado = models.BooleanField("certificado de calidad", default=False)
    remision = models.BooleanField("remisión o factura", default=False)
    observaciones = models.TextField(blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.ESPERANDO)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.codigo} · {self.material.nombre} · lote {self.lote_proveedor}"


class Entrega(models.Model):
    """Etapa 3: el Almacenista entrega los materiales de una orden a producción."""

    orden = models.OneToOneField("produccion.OrdenProduccion", on_delete=models.PROTECT, related_name="entrega")
    entregado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Entrega {self.orden.codigo}"


class EntregaDetalle(models.Model):
    """Cada material entregado, con el lote de donde salió (para la trazabilidad)."""

    entrega = models.ForeignKey(Entrega, on_delete=models.PROTECT, related_name="detalles")
    llegada = models.ForeignKey(Llegada, on_delete=models.PROTECT, related_name="entregas", verbose_name="lote de origen")
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])

    class Meta:
        verbose_name = "detalle de entrega"
        verbose_name_plural = "detalles de entrega"


class LoteProducto(models.Model):
    """Lote de producto terminado. Se crea cuando el Jefe aprueba la producción."""

    class Estado(models.TextChoices):
        POR_LIBERAR = "POR_LIBERAR", "Esperando a Calidad"
        LIBERADO = "LIBERADO", "Liberado"
        NO_CONFORME = "NO_CONFORME", "No conforme"
        DESPACHADO_PARCIAL = "DESPACHADO_PARCIAL", "Despachado en parte"
        DESPACHADO = "DESPACHADO", "Despachado"

    codigo = models.CharField("código", max_length=20, unique=True)  # L-2026-014
    orden = models.OneToOneField("produccion.OrdenProduccion", on_delete=models.PROTECT, related_name="lote")
    tamano = models.ForeignKey("catalogo.Tamano", on_delete=models.PROTECT, verbose_name="producto y tamaño")
    cantidad = models.PositiveIntegerField("cantidad (unidades)")
    fecha_produccion = models.DateField("fecha de producción")
    vencimiento = models.DateField("fecha de vencimiento")
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.POR_LIBERAR)
    ubicacion = models.CharField("ubicación en bodega", max_length=40, blank=True)  # Estante B-3

    class Meta:
        ordering = ["-fecha_produccion"]
        verbose_name = "lote de producto"
        verbose_name_plural = "lotes de producto"

    def __str__(self):
        return f"{self.codigo} · {self.tamano}"


class Despacho(models.Model):
    """El Almacenista despacha un lote liberado a un cliente."""

    lote = models.ForeignKey(LoteProducto, on_delete=models.PROTECT, related_name="despachos")
    cliente = models.ForeignKey("catalogo.Cliente", on_delete=models.PROTECT, related_name="despachos")
    cantidad = models.PositiveIntegerField("cantidad (unidades)", validators=[MinValueValidator(1)])
    factura = models.CharField(max_length=30)
    vehiculo = models.CharField("vehículo (placa)", max_length=15, blank=True)
    conductor = models.CharField(max_length=100, blank=True)
    despachado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.lote.codigo} → {self.cliente} · {self.cantidad}"


class Movimiento(models.Model):
    """El historial. Solo se agregan filas: la base de datos no deja editarlas ni borrarlas."""

    class Etapa(models.TextChoices):
        RECEPCION = "RECEPCION", "Recepción de materia prima e insumo"
        REVISION = "REVISION", "Revisión de calidad"
        ORDEN = "ORDEN", "Orden de producción"
        PRODUCCION = "PRODUCCION", "Producción"
        LIBERACION = "LIBERACION", "Liberación de producto terminado"
        DESPACHO = "DESPACHO", "Despacho"
        ADMINISTRACION = "ADMINISTRACION", "Administración"

    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    etapa = models.CharField(max_length=15, choices=Etapa.choices)
    accion = models.CharField("qué hizo", max_length=255)
    paso = models.BooleanField("pasó")
    motivo = models.TextField(blank=True)
    referencia = models.CharField(max_length=30, help_text="Lote u orden, para la trazabilidad.")

    class Meta:
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y %H:%M} · {self.usuario} · {self.accion}"
