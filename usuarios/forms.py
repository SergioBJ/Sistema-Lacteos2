from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Usuario


class UsuarioBaseForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "username", "email", "rol"]
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellido",
            "username": "Usuario",
            "email": "Correo electrónico",
            "rol": "Rol",
        }
        help_texts = {
            "username": "Con este nombre entra al sistema. Sin espacios.",
            "rol": "Cada persona tiene un solo rol.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True


class UsuarioCrearForm(UsuarioBaseForm):
    password = forms.CharField(
        label="Contraseña temporal", widget=forms.PasswordInput,
        help_text="Dásela a la persona; puede cambiarla con «¿Olvidaste tu contraseña?».",
    )

    def clean_password(self):
        clave = self.cleaned_data["password"]
        validate_password(clave)
        return clave

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data["password"])
        if commit:
            usuario.save()
        return usuario


class UsuarioEditarForm(UsuarioBaseForm):
    password = forms.CharField(
        label="Nueva contraseña temporal", widget=forms.PasswordInput, required=False,
        help_text="Déjala vacía para no cambiarla.",
    )

    def clean_password(self):
        clave = self.cleaned_data["password"]
        if clave:
            validate_password(clave, self.instance)
        return clave

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if self.cleaned_data.get("password"):
            usuario.set_password(self.cleaned_data["password"])
        if commit:
            usuario.save()
        return usuario


# ---------------------------------------------------------------------
# Recuperar contraseña: se puede escribir el usuario o el correo
# ---------------------------------------------------------------------
from django.contrib.auth.forms import PasswordResetForm  # noqa: E402
from django.db.models import Q  # noqa: E402


class RecuperarForm(PasswordResetForm):
    email = forms.CharField(
        label="Usuario o correo", max_length=254,
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )

    def get_users(self, dato):
        """Busca por usuario o por correo. El enlace siempre llega al correo registrado del usuario."""
        dato = dato.strip()
        candidatos = Usuario.objects.filter(Q(username__iexact=dato) | Q(email__iexact=dato), is_active=True)
        return (u for u in candidatos if u.has_usable_password() and u.email)
