"""
Modèle abstrait de base pour tout Poufiret.
Toutes les tables métier héritent de ModeleBase :
- id en UUID (non devinable, pratique pour scaling/fusion)
- horodatage création / modification automatique
"""
import uuid
from django.db import models


class ModeleBase(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-cree_le']
