"""Abstraction de la source de position d'un livreur.

Meme principe que la couche SMS (EnvoyeurSMS / FauxSMS) : le code metier
enregistre une position via `enregistrer_position(livreur, lat, lng, source)`
sans savoir si elle vient du telephone du livreur ou d'un transpondeur.
Basculer de l'un a l'autre = changer `source_position` sur le livreur.
Aucune logique metier a reecrire le jour du transpondeur.
"""
from abc import ABC, abstractmethod
from django.contrib.gis.geos import Point
from django.utils import timezone


class SourcePosition(ABC):
    """Contrat commun a toutes les sources de position."""
    nom = 'abstrait'

    @abstractmethod
    def valider(self, livreur, latitude, longitude):
        """Verifie que cette source a le droit de poser la position de ce
        livreur. Leve ValueError sinon. A specialiser par source."""
        raise NotImplementedError


class SourceTelephone(SourcePosition):
    """La position vient de l'app livreur (telephone authentifie par JWT).
    Le livreur ne peut mettre a jour QUE sa propre position."""
    nom = 'telephone'

    def valider(self, livreur, latitude, longitude):
        # L'auth JWT garantit deja l'identite ; rien de plus a verifier ici.
        return True


class SourceTranspondeur(SourcePosition):
    """La position vient d'un boitier materiel, identifie par transpondeur_id.
    On verifie que le boitier correspond bien a ce livreur."""
    nom = 'transpondeur'

    def __init__(self, transpondeur_id=''):
        self.transpondeur_id = transpondeur_id

    def valider(self, livreur, latitude, longitude):
        if not livreur.transpondeur_id:
            raise ValueError("Ce livreur n'a pas de transpondeur configure.")
        if self.transpondeur_id != livreur.transpondeur_id:
            raise ValueError('Transpondeur non reconnu pour ce livreur.')
        return True


# Registre des sources disponibles (comme BACKENDS pour le SMS).
SOURCES = {
    'telephone': SourceTelephone,
    'transpondeur': SourceTranspondeur,
}


def enregistrer_position(livreur, latitude, longitude, source):
    """Point d'entree unique : valide via la source puis ecrit la position.
    `source` est une instance de SourcePosition. Retourne le livreur maj."""
    source.valider(livreur, latitude, longitude)
    # PostGIS : Point(x=longitude, y=latitude).
    livreur.position = Point(float(longitude), float(latitude), srid=4326)
    livreur.position_maj_le = timezone.now()
    livreur.save(update_fields=['position', 'position_maj_le'])
    return livreur
