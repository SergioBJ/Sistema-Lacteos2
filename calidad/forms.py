from django import forms

from .models import Parametro


class ParametroForm(forms.ModelForm):
    class Meta:
        model = Parametro
        fields = ["nombre", "metodo", "minimo", "maximo", "unidad"]
        labels = {"metodo": "Cómo se evalúa"}
        help_texts = {
            "nombre": "Ejemplo: Acidez, Grasa, Antibióticos.",
            "metodo": "Ejemplo: titulación, prueba rápida, termómetro.",
            "unidad": "Ejemplo: %, °C, °Th.",
            "maximo": "Para pruebas de sí/no (como antibióticos) usa 0 = negativo, 1 = positivo y máximo 0.",
        }

    def __init__(self, *args, destino=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.destino = destino  # {"material": obj} o {"tipo_producto": obj}

    def clean(self):
        datos = super().clean()
        minimo, maximo = datos.get("minimo"), datos.get("maximo")
        if minimo is None and maximo is None:
            raise forms.ValidationError("Pon al menos un límite: mínimo, máximo o ambos.")
        if minimo is not None and maximo is not None and minimo > maximo:
            self.add_error("maximo", "El máximo no puede ser menor que el mínimo.")
        nombre = (datos.get("nombre") or "").strip()
        if nombre and self.destino:
            repetido = Parametro.objects.filter(nombre__iexact=nombre, **self.destino)
            if self.instance.pk:
                repetido = repetido.exclude(pk=self.instance.pk)
            if repetido.exists():
                self.add_error("nombre", "Este parámetro ya existe para este material o producto.")
        return datos

    def save(self, commit=True):
        parametro = super().save(commit=False)
        for campo, valor in (self.destino or {}).items():
            setattr(parametro, campo, valor)
        if commit:
            parametro.save()
        return parametro
