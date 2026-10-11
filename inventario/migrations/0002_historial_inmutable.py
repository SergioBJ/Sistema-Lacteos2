"""Fase 5: candado en la base de datos.

El historial (tabla inventario_movimiento) solo acepta filas nuevas.
Cualquier intento de editar, borrar o vaciar la tabla es rechazado por
PostgreSQL, venga del programa, del panel /admin o del propio Supabase.
"""
from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION bloquear_cambios_historial() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'El historial no se puede modificar ni borrar';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER historial_inmutable
BEFORE UPDATE OR DELETE ON inventario_movimiento
FOR EACH ROW EXECUTE FUNCTION bloquear_cambios_historial();

CREATE TRIGGER historial_no_vaciar
BEFORE TRUNCATE ON inventario_movimiento
FOR EACH STATEMENT EXECUTE FUNCTION bloquear_cambios_historial();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS historial_no_vaciar ON inventario_movimiento;
DROP TRIGGER IF EXISTS historial_inmutable ON inventario_movimiento;
DROP FUNCTION IF EXISTS bloquear_cambios_historial();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("inventario", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL),
    ]
