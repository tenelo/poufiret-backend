"""Génère une paire de clés VAPID pour le Web Push de l'admin web.

    docker exec -i backend-poufiret python manage.py generer_cles_vapid

Affiche les lignes à copier dans .env (rien n'est écrit) :
VAPID_PUBLIC_KEY  : clé publique (point non compressé, base64url) — donnée
                    au navigateur (applicationServerKey / SwPush serverPublicKey) ;
VAPID_PRIVATE_KEY : clé privée brute (32 octets, base64url) — secrète ;
VAPID_SUBJECT     : contact exigé par les services push (mailto: ou https:).
"""
import base64

from django.core.management.base import BaseCommand


def _b64url(octets):
    return base64.urlsafe_b64encode(octets).rstrip(b'=').decode('ascii')


class Command(BaseCommand):
    help = "Génère une paire de clés VAPID (Web Push) à copier dans .env."

    def handle(self, *args, **options):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        cle = ec.generate_private_key(ec.SECP256R1())
        privee = cle.private_numbers().private_value.to_bytes(32, 'big')
        publique = cle.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.stdout.write('# A copier dans .env (garder VAPID_PRIVATE_KEY secrete) :')
        self.stdout.write(f'VAPID_PUBLIC_KEY={_b64url(publique)}')
        self.stdout.write(f'VAPID_PRIVATE_KEY={_b64url(privee)}')
        self.stdout.write('VAPID_SUBJECT=mailto:<adresse de contact>')
