from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    """Usuario del sistema: cada persona tiene un solo rol y un correo único."""

    class Rol(models.TextChoices):
        GERENTE = "GERENTE", "Gerente"
        CALIDAD = "CALIDAD", "Supervisor de Calidad"
        JEFE = "JEFE", "Jefe de Producción"
        ALMACENISTA = "ALMACENISTA", "Almacenista"
        OPERADOR = "OPERADOR", "Operador"

    rol = models.CharField(max_length=20, choices=Rol.choices)
    email = models.EmailField(
        "correo",
        unique=True,
        help_text="Aquí le llega el enlace si olvida su contraseña. No se puede repetir.",
    )

    REQUIRED_FIELDS = ["email", "rol"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_rol_display()})"
