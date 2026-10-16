"""
Gestionnaire d'exceptions personnalisé pour l'API.
Uniformise toutes les erreurs en une forme unique pour Flutter :
{
  "erreur": true,
  "code": <http_status>,
  "message": "<résumé lisible>",
  "details": <détails DRF d'origine>
}
"""
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class ErreurMetier(APIException):
    """Refus métier (ex. quota atteint) au format exact
    {"erreur": true, "code", "message": <message>, "details": <dict tel quel>}.

    Contrairement à une ValidationError levée dans un serializer (dont DRF
    convertit chaque valeur en liste de chaînes), `details` est renvoyé sans
    transformation (entiers conservés) et `message` au premier niveau.
    Peut être levée depuis un serializer (validate) ou une vue."""
    status_code = 400
    default_code = 'erreur_metier'

    def __init__(self, message, details=None, status_code=None):
        super().__init__(detail=message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    # Si DRF ne sait pas gérer l'exception, on laisse remonter (erreur 500).
    if response is None:
        return None

    if isinstance(exc, ErreurMetier):
        response.data = {
            'erreur': True,
            'code': response.status_code,
            'message': exc.message,
            'details': exc.details,
        }
        return response

    detail = response.data
    if isinstance(detail, dict) and 'detail' in detail:
        message = str(detail['detail'])
    else:
        message = 'Une erreur est survenue.'

    response.data = {
        'erreur': True,
        'code': response.status_code,
        'message': message,
        'details': detail,
    }
    return response
