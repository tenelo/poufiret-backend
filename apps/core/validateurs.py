"""
Validateurs reutilisables Poufiret.
"""
import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Fallback si la table ParametresSecurite n'existe pas encore (migration non
# passee) ou en cas d'erreur d'acces base : liste minimale codee en dur.
PINS_INTERDITS = {'0000', '1111', '1234'}


def _est_suite(valeur):
    """True si les 4 chiffres forment une suite croissante ou decroissante
    a pas de 1 (1234, 2345, 4321, 9876...)."""
    chiffres = [int(c) for c in valeur]
    ecarts = {chiffres[i + 1] - chiffres[i] for i in range(3)}
    return ecarts == {1} or ecarts == {-1}


def _config_securite():
    """Charge (pins_interdits, bloquer_suites) depuis la base, avec fallback."""
    try:
        from apps.users.models import ParametresSecurite
        params = ParametresSecurite.obtenir()
        pins = set(params.pins_interdits or []) or PINS_INTERDITS
        return pins, params.bloquer_suites
    except Exception:
        # Table absente, migration non passee, ou tout autre souci : on
        # retombe sur la liste en dur, sans blocage des suites.
        return PINS_INTERDITS, False


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
    valeur = str(valeur)
    pins_interdits, bloquer_suites = _config_securite()
    if valeur in pins_interdits:
        raise ValidationError(
            _('Ce code PIN est trop facile a deviner. Choisissez-en un autre.'),
            code='pin_trivial',
        )
    if bloquer_suites and _est_suite(valeur):
        raise ValidationError(
            _('Evitez les suites de chiffres (1234, 4321...). '
              'Choisissez un code moins previsible.'),
            code='pin_suite',
        )
    return valeur
