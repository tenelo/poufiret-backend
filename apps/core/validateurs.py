"""
Validateurs reutilisables Poufiret.
"""
import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# PIN trop faciles a deviner : on les refuse.
PINS_INTERDITS = {
    '0000', '1111', '1234',}


def valider_pin(valeur):
    """
    Valide un PIN Poufiret : exactement 4 chiffres, pas un PIN trivial.
    A utiliser a l'inscription, au changement et a la reinitialisation.
    Leve ValidationError sinon.
    """
    if valeur is None or not re.fullmatch(r'\d{4}', str(valeur)):
        raise ValidationError(
            _('Le code PIN doit contenir exactement 4 chiffres.'),
            code='pin_format',
        )
    if str(valeur) in PINS_INTERDITS:
        raise ValidationError(
            _('Ce code PIN est trop facile à deviner. Choisissez-en un autre.'),
            code='pin_trivial',
        )
    return str(valeur)
