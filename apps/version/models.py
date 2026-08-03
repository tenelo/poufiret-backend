"""Contrôle de version de l'app mobile (force update).

Un singleton éditable en admin. L'app envoie sa version au démarrage ;
le backend répond à_jour / conseillée / obligatoire. Le blocage effectif
(écran vers le store) est décidé côté Flutter, uniquement si 'obligatoire'.
"""
from django.db import models

from apps.core.models import ModeleBase


def _en_triplet(version):
    """'1.10.3' -> (1, 10, 3). Compare numeriquement, pas en texte.

    Robustesse : composants manquants -> 0 ; non numeriques -> 0.
    Ainsi '1.2' devient (1, 2, 0) et une saisie douteuse ne casse rien.
    """
    parts = (version or '').strip().split('.')
    triplet = []
    for i in range(3):
        try:
            triplet.append(int(parts[i]))
        except (IndexError, ValueError):
            triplet.append(0)
    return tuple(triplet)


class ControleVersion(ModeleBase):
    """Paramètres de version de l'app (ligne unique, singleton)."""

    version_min_obligatoire = models.CharField(
        'version minimale obligatoire', max_length=20, default='1.0.0',
        help_text='En dessous de cette version, la mise à jour est imposée '
                  '(app bloquée vers le store).',
    )
    version_conseillee = models.CharField(
        'version conseillée', max_length=20, default='1.0.0',
        help_text='En dessous, on suggère la mise à jour sans bloquer.',
    )
    lien_store_android = models.URLField(
        'lien Play Store (Android)', blank=True,
    )
    lien_store_ios = models.URLField(
        'lien App Store (iOS)', blank=True,
    )
    message = models.CharField(
        'message affiché', max_length=255, blank=True,
        help_text='Facultatif. Ex. « Une nouvelle version corrige des bugs. »',
    )

    class Meta:
        verbose_name = 'contrôle de version'
        verbose_name_plural = 'contrôle de version'

    def save(self, *args, **kwargs):
        # Singleton : on force une seule ligne.
        existant = self.__class__.objects.first()
        if existant and not self.pk:
            self.pk = existant.pk
        super().save(*args, **kwargs)

    @classmethod
    def obtenir(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj

    def statut_pour(self, version_app):
        """Retourne 'a_jour' | 'conseillee' | 'obligatoire' pour une version."""
        v = _en_triplet(version_app)
        if v < _en_triplet(self.version_min_obligatoire):
            return 'obligatoire'
        if v < _en_triplet(self.version_conseillee):
            return 'conseillee'
        return 'a_jour'

    def lien_pour(self, plateforme):
        """Lien store adapté à la plateforme ('android' / 'ios')."""
        if (plateforme or '').lower() == 'ios':
            return self.lien_store_ios
        return self.lien_store_android

    def __str__(self):
        return (f'Version min {self.version_min_obligatoire} / '
                f'conseillée {self.version_conseillee}')
