"""Borra los datos de prueba del sistema SIN tocar los usuarios.

Uso (desde la terminal, nunca desde la aplicación):

    python manage.py limpiar_datos            -> borra los movimientos de prueba
                                                 (llegadas, revisiones, órdenes, producción,
                                                 lotes, despachos e historial).
                                                 Conserva materiales, productos, proveedores,
                                                 clientes, parámetros y fórmulas.

    python manage.py limpiar_datos --todo     -> además borra materiales, productos, tamaños,
                                                 proveedores, clientes, parámetros y fórmulas.

Los usuarios nunca se borran. Pide escribir BORRAR para confirmar.

Ojo: el historial está protegido en la base de datos para que nadie lo borre.
Este comando desactiva esa protección solo mientras borra y la vuelve a activar
al terminar. Úsalo únicamente para limpiar datos de prueba antes de empezar a
trabajar con datos reales.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from calidad.models import Liberacion, Parametro, ResultadoLiberacion, ResultadoRevision, RevisionMaterial
from catalogo.models import Cliente, Material, Producto, Proveedor, Tamano, TipoProducto
from inventario.models import Despacho, Entrega, EntregaDetalle, Llegada, LoteProducto, Movimiento
from produccion.models import (
    FormulaEmpaque, FormulaLimpieza, FormulaMateria, OrdenProduccion,
    RegistroProduccion, RevisionJefe, ValorProceso,
)

# En este orden: primero lo que depende de otras tablas.
MOVIMIENTOS_DE_PRUEBA = [
    ("Historial (movimientos)", Movimiento),
    ("Despachos", Despacho),
    ("Resultados de liberación", ResultadoLiberacion),
    ("Liberaciones", Liberacion),
    ("Lotes de producto", LoteProducto),
    ("Revisiones del jefe", RevisionJefe),
    ("Valores del proceso", ValorProceso),
    ("Registros de producción", RegistroProduccion),
    ("Detalles de entrega", EntregaDetalle),
    ("Entregas a producción", Entrega),
    ("Órdenes de producción", OrdenProduccion),
    ("Resultados de revisión", ResultadoRevision),
    ("Revisiones de material", RevisionMaterial),
    ("Llegadas de material", Llegada),
]
DATOS_BASE = [
    ("Fórmulas · empaque", FormulaEmpaque),
    ("Fórmulas · materia prima", FormulaMateria),
    ("Fórmulas · limpieza", FormulaLimpieza),
    ("Parámetros de calidad", Parametro),
    ("Tamaños", Tamano),
    ("Productos terminados", Producto),
    ("Tipos de producto", TipoProducto),
    ("Proveedores", Proveedor),
    ("Clientes", Cliente),
    ("Materiales", Material),
]
TRIGGERS_HISTORIAL = ["historial_inmutable", "historial_no_vaciar"]


class Command(BaseCommand):
    help = "Borra los datos de prueba sin borrar los usuarios."

    def add_arguments(self, parser):
        parser.add_argument("--todo", action="store_true",
                            help="También borra materiales, productos, proveedores, clientes, parámetros y fórmulas.")
        parser.add_argument("--si", action="store_true", help="No pedir confirmación.")

    def handle(self, *args, **opciones):
        tablas = MOVIMIENTOS_DE_PRUEBA + (DATOS_BASE if opciones["todo"] else [])

        self.stdout.write(self.style.WARNING("\nSe van a BORRAR estos datos (los usuarios NO se tocan):\n"))
        total = 0
        for nombre, modelo in tablas:
            n = modelo.objects.count()
            total += n
            self.stdout.write(f"  - {nombre}: {n}")
        if not opciones["todo"]:
            self.stdout.write("\nSe conservan: materiales, productos, tamaños, proveedores, clientes, parámetros y fórmulas.")
        if total == 0:
            self.stdout.write(self.style.SUCCESS("\nNo hay nada que borrar."))
            return

        if not opciones["si"]:
            respuesta = input('\nEsto NO se puede deshacer. Escribe BORRAR para confirmar: ')
            if respuesta.strip() != "BORRAR":
                raise CommandError("Cancelado. No se borró nada.")

        with transaction.atomic():
            with connection.cursor() as c:
                # Se quita el candado del historial solo durante esta operación.
                for t in TRIGGERS_HISTORIAL:
                    c.execute(f"ALTER TABLE inventario_movimiento DISABLE TRIGGER {t}")
            for nombre, modelo in tablas:
                modelo.objects.all().delete()
            with connection.cursor() as c:
                # Y se vuelve a poner. Si algo falla antes, todo se revierte y el candado queda como estaba.
                for t in TRIGGERS_HISTORIAL:
                    c.execute(f"ALTER TABLE inventario_movimiento ENABLE TRIGGER {t}")

        self.stdout.write(self.style.SUCCESS(f"\nListo: se borraron {total} registros. Los usuarios siguen intactos "
                                             "y el historial volvió a quedar protegido."))
