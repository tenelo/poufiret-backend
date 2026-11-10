"""Rendu JSON de l'API (REST_FRAMEWORK.DEFAULT_RENDERER_CLASSES)."""
from rest_framework.renderers import JSONRenderer

from .demo import nettoyer_donnees


class JSONRendererSansDemo(JSONRenderer):
    """JSONRenderer standard, dont la sortie ne contient jamais le marqueur
    des données de démonstration (apps.core.demo) — un seul point
    d'application pour toutes les réponses, publiques et admin."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return super().render(nettoyer_donnees(data), accepted_media_type, renderer_context)
