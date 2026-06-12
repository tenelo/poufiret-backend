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
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    # Si DRF ne sait pas gérer l'exception, on laisse remonter (erreur 500).
    if response is None:
        return None

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
