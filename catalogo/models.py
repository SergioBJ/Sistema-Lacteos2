"""Datos base que crea el Gerente: materiales, productos, tamaños, proveedores y clientes."""
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Unidad(models.TextChoices):
    LITRO = "L", "litros"
    MILILITRO = "ml", "mililitros"
    KILO = "kg", "kilos"
    GRAMO = "g", "gramos"
    UNIDAD = "und", "unidades"


class Material(models.Model):
    """Lo que entra a la planta: materia prima, insumo de empaque o desinfectante."""

    class Tipo(models.TextChoices):
        MATERIA_PRIMA = "MATERIA_PRIMA", "Materia prima"
        EMPAQUE = "EMPAQUE", "Insumo de empaque"
        DESINFECTANTE = "DESINFECTANTE", "Desinfectante"

    codigo = models.CharField("código", max_length=20, unique=True)  # MP-001
    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    unidad = models.CharField(max_length=5, choices=Unidad.choices)
    stock_minimo = models.DecimalField(
        "stock mínimo", max_digits=12, decimal_places=2, default=0,
        validators=[MinValueValidator(Decimal("0"))],
    )
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["tipo", "nombre"]
        verbose_name_plural = "materiales"

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


class TipoProducto(models.Model):
    """Tipo de producto terminado (Leche en polvo entera, Leche deslactosada...).

    Calidad define los parámetros por tipo, no por marca ni por tamaño.
    """

    nombre = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "tipo de producto"
        verbose_name_plural = "tipos de producto"

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    """Producto terminado de una marca. Agrupa todos sus tamaños."""

    tipo = models.ForeignKey(TipoProducto, on_delete=models.PROTECT, related_name="productos")
    marca = models.CharField(max_length=80)
    vida_util_meses = models.PositiveIntegerField("vida útil (meses)")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["tipo__nombre", "marca"]
        constraints = [
            models.UniqueConstraint(fields=["tipo", "marca"], name="producto_unico_por_marca"),
        ]

    def __str__(self):
        return f"{self.tipo} · {self.marca}"


class Tamano(models.Model):
    """Un tamaño de un producto: saco 25 kg, bolsa 900 g, 1 L..."""

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="tamanos")
    cantidad = models.DecimalField(max_digits=10, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    unidad = models.CharField(max_length=5, choices=Unidad.choices)
    empaque = models.CharField(max_length=40)  # Bolsa, Saco, Caja...
    codigo = models.CharField("código", max_length=20, unique=True)  # LAC-010
    stock_minimo = models.PositiveIntegerField("stock mínimo (unidades)", default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["producto", "cantidad"]
        verbose_name = "tamaño"
        verbose_name_plural = "tamaños"
        constraints = [
            models.UniqueConstraint(fields=["producto", "cantidad", "unidad"], name="tamano_unico_por_producto"),
        ]

    def __str__(self):
        cantidad = f"{self.cantidad:g}".replace(".", ",")
        return f"{self.producto} · {self.empaque} {cantidad} {self.unidad}"

    @property
    def peso_kg(self):
        """Peso (o volumen en litros) de una unidad, para calcular las fórmulas."""
        factores = {"kg": Decimal("1"), "g": Decimal("0.001"), "L": Decimal("1"), "ml": Decimal("0.001")}
        return self.cantidad * factores.get(self.unidad, Decimal("1"))


class Proveedor(models.Model):
    nit = models.CharField("NIT", max_length=20, unique=True)
    nombre = models.CharField(max_length=150)
    telefono = models.CharField("teléfono", max_length=30, blank=True)
    correo = models.EmailField(blank=True)
    direccion = models.CharField("dirección", max_length=200, blank=True)
    materiales = models.ManyToManyField(
        Material, related_name="proveedores", verbose_name="qué suministra",
        help_text="Filtra la lista de proveedores cuando el Almacenista registra una llegada.",
    )
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "proveedores"

    def __str__(self):
        return self.nombre


class Cliente(models.Model):
    nit = models.CharField("NIT", max_length=20, unique=True)
    nombre = models.CharField(max_length=150)
    ciudad = models.CharField(max_length=80, blank=True)
    telefono = models.CharField("teléfono", max_length=30, blank=True)
    correo = models.EmailField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre
