"""Envía los correos del sistema por la API web de Brevo (https://www.brevo.com).

Por qué: el plan gratis de Render no deja salir conexiones SMTP (puertos 25, 465 y 587),
así que Gmail por SMTP no funciona allá. Brevo se usa por internet normal (HTTPS),
que sí está permitido, y su plan gratis alcanza de sobra para recuperar contraseñas.

No necesita librerías extra: usa urllib, que viene con Python.
"""
import json
import logging
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)
URL_BREVO = "https://api.brevo.com/v3/smtp/email"


class BrevoBackend(BaseEmailBackend):
    def __init__(self, api_key=None, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.api_key = api_key

    def _enviar(self, mensaje):
        nombre, correo = parseaddr(mensaje.from_email or settings.DEFAULT_FROM_EMAIL)
        datos = {
            "sender": {"email": correo, "name": nombre or "Sistema PROLAC"},
            "to": [{"email": parseaddr(d)[1]} for d in mensaje.to],
            "subject": mensaje.subject,
            "textContent": mensaje.body,
        }
        for contenido, tipo in getattr(mensaje, "alternatives", []) or []:
            if tipo == "text/html":
                datos["htmlContent"] = contenido
        peticion = urllib.request.Request(
            URL_BREVO, data=json.dumps(datos).encode("utf-8"), method="POST",
            headers={"api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            cuerpo = respuesta.read().decode("utf-8", "ignore")
            logger.info("[correo] Brevo aceptó el correo para %s · respuesta %s %s",
                        ", ".join(mensaje.to), respuesta.status, cuerpo)
            return 200 <= respuesta.status < 300

    def send_messages(self, email_messages):
        enviados = 0
        for mensaje in email_messages:
            try:
                if self._enviar(mensaje):
                    enviados += 1
            except (urllib.error.URLError, OSError) as error:
                detalle = error.read().decode("utf-8", "ignore") if isinstance(error, urllib.error.HTTPError) else ""
                logger.error("[correo] Brevo NO envió el correo a %s · %s · %s", ", ".join(mensaje.to), error, detalle)
                if not self.fail_silently:
                    raise
        return enviados
