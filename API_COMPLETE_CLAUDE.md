# API Poufiret — Référence exhaustive pour le front Angular

Document généré par lecture exhaustive du code (urls.py / views.py / serializers.py / modules annexes) de chaque app Django, sans exécution ni modification du code. Toutes les routes sont préfixées par `/api/v1/` (cf. `poufiret_backend/urls.py`).

Format des erreurs le plus courant dans le projet : `{"erreur": true, "message": "..."}` (parfois `{"detail": "..."}` pour les vues DRF génériques ou simplejwt). Chaque section précise les cas particuliers.

## Sommaire

1. [App users (auth) — /api/v1/auth/](#app-users-auth--apiv1auth)
2. [App catalog — /api/v1/catalogue/](#app-catalog--apiv1catalogue)
3. [App social — /api/v1/social/](#app-social--apiv1social)
4. [App orders — /api/v1/orders/](#app-orders--apiv1orders)
5. [App messaging — /api/v1/messaging/](#app-messaging--apiv1messaging)
6. [App livreurs — /api/v1/livreurs/](#app-livreurs--apiv1livreurs)
7. [App livraison — /api/v1/livraison/](#app-livraison--apiv1livraison)
8. [App payments — /api/v1/payments/](#app-payments--apiv1payments)
9. [App notifications — /api/v1/notifications/](#app-notifications--apiv1notifications)
10. [App analytics — /api/v1/analytics/](#app-analytics--apiv1analytics)
11. [App publicites — /api/v1/publicites/](#app-publicites--apiv1publicites)
12. [App geo — /api/v1/geo/](#app-geo--apiv1geo)
13. [App version — /api/v1/version/](#app-version--apiv1version)
14. [App administration — /api/v1/administration/](#app-administration--apiv1administration)

---

## App users (auth) — /api/v1/auth/

**Note générale sur les permissions** : `permissions.AllowAny` = accès public. `permissions.IsAuthenticated` = JWT valide requis (header `Authorization: Bearer <access>`). Pour `ConnexionView` et le refresh JWT (`TokenRefreshView`), la classe parente `TokenViewBase` de `rest_framework_simplejwt` définit `permission_classes = ()` (tuple vide) — c'est-à-dire **aucune vérification de permission appliquée**, ce qui revient en pratique à un accès public, mais ce n'est pas littéralement `AllowAny`.

### POST /inscription/

- **Vue** : `InscriptionView` (`generics.CreateAPIView`)
- **Permission** : `AllowAny` — public
- **Description** : Créer un compte utilisateur (rôle `client` forcé côté serveur). Le mot de passe est en réalité un PIN à 4 chiffres.
- **Serializer d'entrée** : `InscriptionSerializer`

| Champ | Type | Requis | Remarque |
|---|---|---|---|
| `telephone` | string | requis | identifiant unique |
| `username` | string | requis | |
| `first_name` | string | optionnel | |
| `last_name` | string | optionnel | |
| `password` | string | requis | write_only, `min_length=4`, `max_length=4`, validé par `valider_pin` |
| `departement` | int (FK id) | optionnel | |
| `tranche_age` | choices | optionnel | `moins_18`, `18_24`, `25_34`, `35_44`, `45_54`, `55_plus` |
| `sexe` | choices | optionnel | `homme`, `femme`, `non_precise` |

- **Sortie** (custom, construite dans la vue) : `access` (read_only), `refresh` (read_only), `utilisateur` (read_only, objet `UtilisateurSerializer`). Statut `201`.

### POST /connexion/

- **Vue** : `ConnexionView` (hérite de `TokenObtainPairView`)
- **Permission** : héritée de `TokenViewBase` → `permission_classes = ()` (public)
- **Description** : Connexion par téléphone + PIN. Enregistre/actualise une `SessionAppareil` si des infos d'appareil sont fournies.
- **Serializer** : `ConnexionSerializer` (hérite de `TokenObtainPairSerializer`)
- **Entrée** : `telephone` (requis), `password` (requis, le PIN). Champs additionnels lus directement dans `request.data` par la vue (non validés par serializer) : `appareil_id` (optionnel), `appareil_nom` (optionnel), `plateforme` (optionnel, `android`/`ios`/`web`/`autre`, défaut `autre`).
- **Sortie** : `access` (read_only), `refresh` (read_only), `utilisateur` (read_only, objet `UtilisateurSerializer`). Échec : erreur standard simplejwt (`detail` ou `non_field_errors`).

### POST /otp/demander/

- **Vue** : `DemanderOTPView` (`APIView`)
- **Permission** : `AllowAny`
- **Description** : Demande un code OTP par SMS. Pour `but=inscription`, si le numéro est déjà dans `NumeroVerifie`, aucun SMS n'est envoyé. Pour `but=reinit_pin`, un OTP est envoyé uniquement si un compte existe pour ce numéro.
- **Serializer** : `DemandeOTPSerializer`
- **Entrée** : `telephone` (requis, doit commencer par `+`), `but` (optionnel, `ChoiceField`, défaut `inscription` ; valeurs `inscription`/`reinit_pin`).
- **Sortie** (dict construit, non-ModelSerializer) : `deja_verifie` (read_only), `compte_existe` (read_only), `otp_envoye` (read_only).
- Erreur : `but=reinit_pin` sans compte existant → `ValidationError` sur `telephone`.

### POST /otp/verifier/

- **Vue** : `VerifierOTPView` (`APIView`)
- **Permission** : `AllowAny`
- **Description** : Vérifie le code OTP. Incrémente les tentatives ; sur succès marque `valide_le`, enregistre le numéro dans `NumeroVerifie` (source `otp`).
- **Serializer** : `VerifierOTPSerializer`
- **Entrée** : `telephone` (requis), `code` (requis, max 4 caractères), `but` (optionnel, défaut `inscription`).
- **Sortie** : `verifie` (read_only, toujours `true` si 200), `message` (read_only).
- Erreurs 400 : aucun code actif, code expiré/trop de tentatives, code incorrect.

### POST /pin/definir/

- **Vue** : `DefinirPINView` (`APIView`)
- **Permission** : `AllowAny`
- **Description** : Définit le PIN (cas inscription) ou le réinitialise (cas `reinit_pin`), après preuve d'un OTP validé récemment (fenêtre `CodeOTP.FENETRE_PREUVE_MINUTES` = 15 min). Renvoie des tokens JWT directement.
- **Serializer** : `DefinirPINSerializer`
- **Entrée** : `telephone` (requis), `password` (requis, PIN 4 chiffres, `valider_pin`), `but` (optionnel, défaut `inscription`), `username`/`first_name`/`last_name` (optionnels, `allow_blank=True`, utilisés seulement si `but=inscription`).
- **Sortie** : `access`, `refresh`, `utilisateur` (tous read_only, objet `UtilisateurSerializer`). Statut `200`.

### POST /pin/changer/

- **Vue** : `ChangerPINView` (`APIView`)
- **Permission** : `IsAuthenticated`
- **Description** : Change le PIN d'un utilisateur connecté (ancien PIN + nouveau PIN, pas d'OTP requis).
- **Serializer** : `ChangerPINSerializer`
- **Entrée** : `ancien_pin` (requis, write_only, 4 caractères, doit correspondre au PIN actuel), `nouveau_pin` (requis, write_only, 4 caractères, `valider_pin`, différent de l'ancien).
- **Sortie** : `access`, `refresh` (tokens régénérés), `utilisateur` (tous read_only). Effet de bord : `pin_par_defaut` repassé à `False`.

### POST /rafraichir/

- **Vue** : `TokenRefreshView` (standard `rest_framework_simplejwt`, non surchargée)
- **Permission** : `permission_classes = ()` (public)
- **Entrée** : `{"refresh": "<token>"}`
- **Sortie** : `{"access": "<token>"}`, plus `{"refresh": "<nouveau token>"}` si `ROTATE_REFRESH_TOKENS=True` côté settings (non vérifié).

### POST /deconnexion/

- **Vue** : `DeconnexionView` (`APIView`)
- **Permission** : `IsAuthenticated`
- **Description** : Blackliste le refresh token fourni et désactive la session appareil correspondante si `appareil_id` fourni.
- **Serializer** : `LogoutSerializer`
- **Entrée** : `refresh` (requis), `appareil_id` (optionnel, lu directement dans `request.data`).
- **Sortie** : `message` (read_only) — `"Déconnexion réussie."`

### GET / PUT / PATCH /moi/

- **Vue** : `MonProfilView` (`generics.RetrieveUpdateAPIView` — pas de DELETE)
- **Permission** : `IsAuthenticated`
- **Description** : Consulter/modifier son propre profil (`get_object` = `request.user`).
- **Serializer** : `UtilisateurSerializer` (entrée = sortie)

| Champ | read_only | Remarque |
|---|---|---|
| `id` | oui | |
| `telephone` | oui | non modifiable ici |
| `username` | non | modifiable |
| `first_name` | non | modifiable |
| `last_name` | non | modifiable |
| `role` | oui | |
| `est_verifie` | oui | |
| `pin_par_defaut` | oui | |
| `langue_preferee` | non | modifiable (défaut `fr`) |
| `token_fcm` | non | modifiable |
| `departement` | non | modifiable (id FK) |
| `departement_nom` | oui | dérivé |
| `region_nom` | oui | dérivé |
| `tranche_age` | non | modifiable |
| `sexe` | non | modifiable |

### POST /devenir-partenaire/

- **Vue** : `DevenirPartenaireView` (`generics.CreateAPIView`)
- **Permission** : `IsAuthenticated`
- **Description** : Un client crée son profil partenaire (auto-inscription). Rôle bascule en `partenaire` immédiatement, mais profil créé `statut=en_attente`, `est_visible=False`. Erreur si profil déjà existant.
- **Serializer d'entrée** : `DevenirPartenaireSerializer`
- **Entrée** : `type_partenaire` (choices : `commercant`, `pharmacien`, `boulanger`, `restaurateur`, `couturier`, `menuisier`, `plombier`, `electricien`, `macon`, `coiffeur`, `libraire`, `hotelier`, `mecanicien`, `loueur_maison`, `loueur_voiture`, `autre` ; défaut modèle `commercant`), `nom_commerce` (requis), `description`/`adresse`/`quartier`/`secteur` (optionnels), `ville` (optionnel, défaut `Ferké`), `departement` (optionnel, FK id), `telephone_pro`/`whatsapp`/`email_pro` (optionnels), `categories` (optionnel, write_only, liste d'IDs — la première devient catégorie principale, sinon déduite du `type_partenaire`).
- **Sortie** : `message` (read_only), `utilisateur` (read_only, objet `UtilisateurSerializer` de `request.user` — pas le profil partenaire créé). Statut `201`.

### POST /partenaires/creer/

- **Vue** : `CreerPartenaireParAdminView` (`APIView`)
- **Permission** : `IsAuthenticated` + `ADroitDe('creer_partenaire')`
- **Description** : Création complète d'un partenaire (`User` + `ProfilPartenaire` `statut=actif`, `est_visible=True`) par un admin habilité. Numéro considéré vérifié de visu, inscrit dans `NumeroVerifie` (source `admin`). PIN aléatoire à 4 chiffres généré (jamais `0000`/`1111`/`1234`), `pin_par_defaut=True`. Journalisé dans `JournalModeration` (best-effort).
- **Serializer d'entrée** : `CreerPartenaireParAdminSerializer`
- **Entrée** : `telephone` (requis, doit commencer par `+`, erreur si compte existant), `prenom`/`nom` (optionnels), `type_partenaire` (requis, `CharField` libre — **pas de validation stricte des choix**, contrairement à `DevenirPartenaireSerializer`), `nom_commerce` (requis), `description`/`adresse`/`quartier`/`secteur`/`ville` (optionnels), `departement` (optionnel, FK id), `telephone_pro`/`whatsapp`/`email_pro` (optionnels), `plan_id` (optionnel, sinon plan `basique` par défaut), `categories` (optionnel, write_only, liste d'IDs).
- **Sortie** (`to_representation` custom) : `partenaire_id` (read_only), `telephone` (read_only), `nom_commerce` (read_only), `statut` (read_only, toujours `actif`), `pin_par_defaut` (read_only — **attention** : ici c'est le PIN en clair string à 4 chiffres, nom de champ trompeur), `message` (read_only, contient le PIN en clair). Statut `201`.

### GET / PUT / PATCH /mon-profil-partenaire/

- **Vue** : `MonProfilPartenaireView` (`generics.RetrieveUpdateAPIView` — pas de DELETE)
- **Permission** : `IsAuthenticated`
- **Description** : Le partenaire connecté consulte/modifie sa vitrine. `PermissionDenied` si pas de profil partenaire.
- **Serializer** : `MonProfilPartenaireSerializer` (entrée = sortie)

| Champ | read_only | Remarque |
|---|---|---|
| `id` | oui | |
| `nom_commerce` | non | modifiable |
| `description` | non | modifiable |
| `logo` | non | modifiable (image) |
| `photo_couverture` | non | modifiable (image) |
| `type_partenaire` | non | modifiable |
| `type_partenaire_libelle` | oui | dérivé |
| `adresse`, `quartier`, `secteur`, `ville`, `description_acces` | non | modifiables |
| `telephone_pro`, `whatsapp`, `email_pro` | non | modifiables |
| `statut` | oui | piloté par l'administration |
| `statut_libelle` | oui | dérivé |
| `est_visible` | oui | piloté par l'administration |
| `badge_certifie` | oui | piloté par l'administration |
| `est_faveur` | oui | piloté par l'administration |
| `plan_libelle` | oui | dérivé |
| `abonnement_fin` | oui | |
| `nb_vues` | oui | |
| `nb_photos_par_article` | oui | dérivé du plan |
| `nb_articles_max` | oui | dérivé du plan |

### GET /mes-categories/

- **Vue** : `MesCategoriesView` (`generics.ListAPIView` — GET seul)
- **Permission** : `IsAuthenticated`
- **Description** : Liste les `PartenaireCategorie` du partenaire connecté, triées par `-est_principale`, `categorie__nom`. Queryset vide si pas de profil partenaire (pas d'erreur).
- **Sortie** : liste de `MaCategorieSerializer` (voir champs ci-dessous).

### GET / PUT / PATCH /mes-categories/\<int:pk\>/

- **Vue** : `MaCategorieDetailView` (`generics.RetrieveUpdateAPIView` — pas de DELETE)
- **Permission** : `IsAuthenticated`
- **Description** : Consulter/modifier une entrée `PartenaireCategorie` du partenaire connecté (sert surtout à changer l'image de couverture propre à cette catégorie).
- **Serializer** : `MaCategorieSerializer`

| Champ | read_only | Remarque |
|---|---|---|
| `id` | oui | |
| `categorie` | oui | non modifiable via PATCH malgré le nom |
| `categorie_nom` | oui | dérivé |
| `categorie_slug` | oui | dérivé |
| `categorie_icone` | oui | dérivé |
| `est_principale` | oui | non modifiable ici |
| `image_couverture` | non | **seul champ réellement modifiable** |

### GET /appareils/

- **Vue** : `MesAppareilsView` (`generics.ListAPIView` — GET seul)
- **Permission** : `IsAuthenticated`
- **Description** : Liste les `SessionAppareil` (actives et inactives) de l'utilisateur connecté.
- **Sortie** (`SessionAppareilSerializer`, tous les champs `read_only_fields = fields`) : `id`, `appareil_nom`, `appareil_id`, `plateforme` (`android`/`ios`/`web`/`autre`), `adresse_ip`, `derniere_activite_le`, `est_active`, `cree_le`.

### POST /appareils/\<uuid:pk\>/revoquer/

- **Vue** : `RevoquerAppareilView` (`APIView`)
- **Permission** : `IsAuthenticated`
- **Description** : Désactive une session appareil précise appartenant à l'utilisateur (`est_active=False`, `revoque_le`, `revoque_par`).
- **Entrée** : aucune (pk UUID dans l'URL).
- **Sortie** : `200 {"message": "Appareil révoqué."}` ou `404 {"erreur": true, "message": "Appareil introuvable."}`.

### GET /partenaires/\<int:pk\>/

- **Vue** : `VitrinePartenaireView` (`generics.RetrieveAPIView` — GET seul)
- **Permission** : `AllowAny` — public
- **Description** : Vitrine publique d'un partenaire. `pk` = id du `ProfilPartenaire` (pas du `User`). Restreint à `statut=actif` et `est_visible=True` (404 sinon).
- **Sortie** (`VitrinePartenaireSerializer`, tous `read_only_fields = fields`) : `id`, `nom_commerce`, `type_partenaire`, `type_partenaire_libelle`, `description`, `logo`, `photo_couverture`, `adresse`, `quartier`, `secteur`, `ville`, `departement` (**nom** du département, string, pas l'id), `region` (nom), `description_acces`, `telephone_pro`, `whatsapp`, `email_pro`, `nombre_likes` (SerializerMethodField), `nb_vues`, `est_like_par_moi` (`false` si anonyme), `est_favori_par_moi` (`false` si anonyme).

**Remarques transverses** :
- `/rafraichir/` : comportement exact de `ROTATE_REFRESH_TOKENS` dépend de `settings.SIMPLE_JWT`, non vérifié.
- Deux chemins d'inscription coexistent : `/inscription/` (direct, sans OTP) et `/otp/...` → `/pin/definir/` (avec preuve OTP) — à clarifier côté produit.
- `CreerPartenaireParAdminSerializer.type_partenaire` n'a aucune validation de choix côté serializer (CharField libre), contrairement à `DevenirPartenaireSerializer`.

---

## App catalog — /api/v1/catalogue/

### Notes générales

- **Pagination** : `StandardPagination` (PageNumberPagination), `?page=N`, `?page_size=N` (max 100, défaut 20), sauf `VideosPartenaireView` (pas de pagination).
- Permission `EstPartenaireProprietaireOuLectureSeule` : lecture (`GET`/`HEAD`/`OPTIONS`) libre pour tous ; écriture réservée à un utilisateur authentifié `role=PARTENAIRE` et propriétaire de l'objet.

### 1. Catégories — `CategorieViewSet` (`ReadOnlyModelViewSet`)

Permission : `AllowAny`.

| Méthode | Chemin | Action | Description |
|---|---|---|---|
| GET | `/api/v1/catalogue/categories/` | list | Catégories racines (`parent__isnull=True`, `est_archivee=False`), triées `ordre`, `nom`. |
| GET | `/api/v1/catalogue/categories/<slug>/` | retrieve | Détail d'une catégorie (`lookup_field='slug'`). |

**Sortie (`CategorieSerializer`)** : `id`, `nom`, `slug`, `description`, `icone`, `image_couverture`, `parent`, `mode_transaction`, `types_articles`, `affiche_catalogue`, `module_flutter`, `ordre`, `est_active`, `nb_partenaires` (SerializerMethodField, `null` pour les enfants imbriqués), `enfants` (SerializerMethodField, récursif, `est_active=True`), `types_partenaire`. Aucune entrée (lecture seule).

### 2. Articles — `ArticleViewSet` (`ModelViewSet`)

Permission : `EstPartenaireProprietaireOuLectureSeule`. `lookup_field='slug'`. Serializer dynamique : `ArticleListeSerializer` (list) / `ArticleDetailSerializer` (autres actions).

Filtres `list` : `?categorie=<id>`, `?partenaire=<id>`, `?type=<produit|plat|service|logement|vehicule>`, `?recherche=<texte>`, `?localites=<id1,id2,...>`.

| Méthode | Chemin | Action | Description |
|---|---|---|---|
| GET | `/api/v1/catalogue/articles/` | list | Liste paginée, `-created_at`. Visibilité selon rôle/portée géographique. |
| POST | `/api/v1/catalogue/articles/` | create | Créer (partenaire connecté). Quota `plan.nb_articles_max` ; slug auto-généré ; `partenaire` forcé serveur. |
| GET | `/api/v1/catalogue/articles/<slug>/` | retrieve | Détail complet. |
| PUT/PATCH | `/api/v1/catalogue/articles/<slug>/` | update/partial_update | Propriétaire uniquement. |
| DELETE | `/api/v1/catalogue/articles/<slug>/` | destroy | Propriétaire uniquement. |

**Sortie liste (`ArticleListeSerializer`)** : `id`, `nom`, `slug`, `type`, `prix`, `prix_promotion`, `pourcentage_reduction` (read-only), `prix_effectif` (read-only), `promotion_valide` (read-only), `est_en_promotion`, `est_disponible`, `nb_vues`, `nb_likes`, `partenaire`, `partenaire_nom` (read-only), `categorie`, `image_principale` (read-only, URL ou `null`).

**Sortie/Entrée détail (`ArticleDetailSerializer`)** : `id`, `nom`, `slug`, `description`, `type`, `prix`, `prix_promotion`, `unite`, `details`, `est_actif`, `est_disponible`, `est_en_promotion`, `pourcentage_reduction`, `prix_effectif`, `promotion_valide`, `temps_preparation_min`, `nb_vues`, `nb_likes`, `nb_commentaires`, `nb_favoris`, `partenaire`, `partenaire_nom`, `categorie`, `section_menu`, `images`, `videos`, `variantes`, `supplements`, `panoramas`, `logement`, `vehicule`, `est_like_par_moi`, `est_favori_par_moi`, `created_at`, `updated_at`.
- `read_only_fields` déclarés : `slug`, `nb_vues`, `nb_likes`, `nb_commentaires`, `nb_favoris`, `partenaire`.
- Read-only additionnels (nested/computed) : `images`, `videos`, `variantes`, `supplements`, `panoramas` (gestion via ViewSets dédiés), `logement`, `vehicule` (gestion via vues dédiées), `est_like_par_moi`, `est_favori_par_moi`, `pourcentage_reduction`, `prix_effectif`, `promotion_valide`, `created_at`, `updated_at`.
- **Entrée réelle** : `nom`, `description`, `type` (`produit|plat|service|logement|vehicule`), `prix`, `prix_promotion`, `unite`, `details`, `est_actif`, `est_disponible`, `est_en_promotion`, `temps_preparation_min`, `categorie`, `section_menu`.

### 3. Images d'article — `ArticleImageViewSet`

Permission : `EstPartenaireProprietaireOuLectureSeule`. Filtre `list` : `?article=<id>`.

CRUD standard sur `/api/v1/catalogue/images/` et `/api/v1/catalogue/images/<pk>/`. Création : le partenaire doit posséder l'article cible ; quota `plan.nb_photos_par_article` appliqué.

**Sortie/Entrée (`ArticleImageSerializer`)** : `id`, `article`, `image`, `legende`, `ordre`, `est_principale`, `est_active`.
- `read_only_fields` : `est_active` (forcé `True` côté serveur à la création).
- Entrée : `article` (requis), `image` (fichier), `legende`, `ordre`, `est_principale`.

### 4. Vidéos d'article — `ArticleVideoViewSet`

Permission : `EstPartenaireProprietaireOuLectureSeule`. Filtre `list` : `?article=<id>`.

CRUD standard sur `/api/v1/catalogue/videos/` et `/api/v1/catalogue/videos/<pk>/`. Création : propriétaire de l'article requis, plan doit avoir `peut_publier_video=True` et `nb_videos_par_article > 0`, quota vérifié ; `est_active` forcé `True` à la création.

**Sortie/Entrée (`ArticleVideoSerializer`)** : `id`, `article`, `article_nom` (read-only), `article_slug` (read-only), `video`, `titre`, `miniature`, `ordre`, `est_active`. Entrée : `article`, `video`, `titre`, `miniature`, `ordre` (`est_active` techniquement modifiable en PATCH/PUT mais forcé `True` à la création).

### 5. Vidéos par partenaire — `VideosPartenaireView`

- **Chemin/méthode** : `GET /api/v1/catalogue/partenaire/<int:partenaire_id>/videos/`
- **Permission** : `permission_classes = []` (équivaut à `AllowAny`)
- **Description** : Toutes les vidéos actives des articles actifs d'un partenaire, triées `article`, `ordre`. Pas de pagination.
- **Sortie** : liste de `ArticleVideoSerializer` (voir §4).

### 6. Variantes — `VarianteViewSet`

Permission : `EstPartenaireProprietaireOuLectureSeule`. Filtre `list` : `?article=<id>`. CRUD standard sur `/api/v1/catalogue/variantes/` et `/<pk>/`.

**Sortie/Entrée (`VarianteSerializer`)** : `id`, `article`, `nom`, `prix_supplement`, `est_par_defaut`, `ordre`, `est_active`. Aucun `read_only_fields` — tout modifiable sauf `id`.

### 7. Suppléments — `SupplementViewSet`

Permission : `EstPartenaireProprietaireOuLectureSeule`. Filtre `list` : `?article=<id>`. CRUD standard sur `/api/v1/catalogue/supplements/` et `/<pk>/`.

**Sortie/Entrée (`SupplementSerializer`)** : `id`, `article`, `nom`, `prix`, `est_optionnel`, `ordre`, `est_actif`. Aucun `read_only_fields` — tout modifiable sauf `id`.

### 8. Panoramas — `PanoramaViewSet`

Permission : `EstPartenaireProprietaireOuLectureSeule`. Filtre `list` : `?article=<id>`. CRUD standard sur `/api/v1/catalogue/panoramas/` et `/<pk>/`.

**Sortie/Entrée (`PanoramaSerializer`)** : `id`, `article`, `image`, `nom_piece`, `ordre`, `est_active`. Aucun `read_only_fields` — tout modifiable sauf `id`.

### 9. Logement — `LogementView`

- **Chemin** : `GET / PUT / PATCH /api/v1/catalogue/articles/<slug>/logement/`
- **Permission** : `EstPartenaireProprietaireOuLectureSeule`. `lookup_field='slug'` (slug de l'article). Pas de POST/DELETE — `get_or_create(article=article)` implicite.
- **Sortie/Entrée (`LogementSerializer`)** : `id`, `article` (read_only, fixé par l'URL), `nb_chambres`, `nb_sdb`, `surface_m2`, `meuble`, `duree_min_jours`, `caution`, `equipements`.

### 10. Véhicule — `VehiculeView`

- **Chemin** : `GET / PUT / PATCH /api/v1/catalogue/articles/<slug>/vehicule/`
- **Permission** : `EstPartenaireProprietaireOuLectureSeule`. Même logique `get_or_create` que Logement.
- **Sortie/Entrée (`VehiculeSerializer`)** : `id`, `article` (read_only), `marque`, `modele`, `annee`, `kilometrage`, `carburant`, `boite_vitesse`, `places`, `mode`.

### 11. Enregistrer une vue — `EnregistrerVueView`

- **Chemin/méthode** : `POST /api/v1/catalogue/articles/<slug>/vue/` (POST uniquement)
- **Permission** : `AllowAny`
- **Description** : Enregistre une consultation (`VueArticle`) sur un article actif, incrémente `nb_vues`, met à jour le profil analytics.
- **Entrée** (non-sérialisé, `request.data`) : `source` (optionnel, `recherche|categorie|carrousel|favoris|chat|lien_direct|autre`, défaut `autre`), `duree_secondes` (optionnel).
- **Sortie** : `201 {"message": "Vue enregistrée."}` ; `404 {"erreur": true, "message": "Article introuvable."}` si non trouvé/inactif.

### 12. Recherche unifiée — `RechercheUnifieeView`

- **Chemin/méthode** : `GET /api/v1/catalogue/recherche/?q=<terme>`
- **Permission** : `permission_classes = []` (≈ `AllowAny`)
- **Entrée (query)** : `q` (si `len < 2`, résultats vides), `localites` (optionnel, CSV).
- **Sortie** (non paginée) : `{categories: [...], partenaires: [...], articles: [...]}`.
  - `categories` (max 10) : `id`, `nom`, `slug`, `icone`, `mode_transaction`, `affiche_catalogue`.
  - `partenaires` (max 15) : `id`, `nom_commerce`, `description`, `logo`, `photo_couverture`, `type_partenaire` (libellé), `departement`.
  - `articles` (max 20) : `id`, `nom`, `slug`, `prix` (str), `prix_promotion` (str/null), `est_en_promotion`, `pourcentage_reduction`, `prix_effectif` (str), `partenaire_nom`, `departement`, `image_principale` (URL/null).
- Effet de bord : si 0 résultat partout, journalisé dans `RechercheSansResultat`.

### 13. Stats de vues partenaire — `StatsVuesPartenaireView`

- **Chemin/méthode** : `GET /api/v1/catalogue/partenaire/stats-vues/`
- **Permission** : `IsAuthenticated` (+ doit avoir un `profil_partenaire`, sinon 403)
- **Sortie** :
```json
{
  "total_vues": 0,
  "articles": [{"article_id":0,"nom":"","slug":"","est_actif":true,"total":0,"jour":0,"semaine":0,"mois":0}]
}
```
Articles triés par `-nb_vues` ; `jour`/`semaine`/`mois` = comptage `VueArticle` sur 1/7/30 jours glissants.

### 14. Carte des partenaires — `CartePartenairesView`

- **Chemin/méthode** : `GET /api/v1/catalogue/carte/partenaires/`
- **Permission** : `permission_classes = []` (≈ `AllowAny`)
- **Entrée (query)** : `categorie` (optionnel, slug, 404 si invalide), `localites` (optionnel, CSV).
- **Sortie** (liste non paginée) : `id`, `nom_commerce`, `logo`, `photo_couverture`, `departement` (nom), `region` (nom), `latitude`, `longitude`, `adresse`, `quartier`, `categorie` (slug de la catégorie "principale"). Filtre : `est_visible=True`, `localisation__isnull=False`, portée géographique, triés `-est_faveur`, `nom_commerce`.

### 15. Partenaires par catégorie — `PartenairesParCategorieView`

- **Chemin/méthode** : `GET /api/v1/catalogue/categories/<slug>/partenaires/`
- **Permission** : `permission_classes = []` (≈ `AllowAny`)
- **Entrée (query)** : `localites` (optionnel, CSV).
- **Sortie** (liste non paginée) : `id`, `nom_commerce`, `description`, `logo`, `photo_couverture`, `departement` (nom), `region` (nom), `latitude`/`longitude` (peuvent être `null`), `adresse`, `quartier`. 404 si slug invalide.

⚠️ **Ambiguïté** : les 3 endpoints "listing partenaires" (recherche, carte, partenaires-par-catégorie) ont chacun un jeu de champs de sortie légèrement différent — à traiter comme 3 DTO distincts côté front.

---

## App social — /api/v1/social/

### Likes / Favoris (toggle)

Toutes héritent de `_ToggleBase` (APIView). Seule `POST` est implémentée (malgré `urls.py` qui déclare `POST/DELETE` — un `DELETE` renverrait `405`). `POST` **bascule** l'état : crée si absent, supprime si présent.

**Réponse commune** : `{"actif": bool, "total": int|null}` (`total` = compteur mis à jour, `null` si pas de compteur dédié pour les partenaires).

| Méthode | Chemin | Vue | Permission | Sortie |
|---|---|---|---|---|
| POST | `/articles/<int:pk>/like/` | `ToggleLikeArticle` | `IsAuthenticated` | `actif`, `total` (`Article.nb_likes`) |
| POST | `/articles/<int:pk>/favori/` | `ToggleFavoriArticle` | `IsAuthenticated` | `actif`, `total` (`Article.nb_favoris`) |
| POST | `/partenaires/<int:pk>/like/` | `ToggleLikePartenaire` | `IsAuthenticated` | `actif`, `total`: `null` |
| POST | `/partenaires/<int:pk>/favori/` | `ToggleFavoriPartenaire` | `IsAuthenticated` | `actif`, `total`: `null` |

### GET /mes-favoris/ — `MesFavorisView`

- **Permission** : `IsAuthenticated`
- **Sortie** :
  - `articles` : liste `FavoriArticleSerializer` — `id` (read-only), `article` (objet imbriqué `_ArticleMiniSerializer` read-only : `id`, `nom`, `slug`, `type`, `prix`, `nb_vues`, `nb_likes`, `partenaire`, `partenaire_nom`, `categorie`), `created_at` (read-only).
  - `partenaires` : liste `FavoriPartenaireSerializer` — `id` (read-only), `partenaire` (objet imbriqué `_PartenaireMiniSerializer` read-only : `id`, `nom_commerce`, `type_partenaire`, `ville`, `quartier`, `logo`), `created_at` (read-only).

### GET /mes-likes/ — `MesLikesView`

- **Permission** : `IsAuthenticated`
- **Sortie** : `{"articles": [id, ...], "partenaires": [id, ...]}` (listes brutes d'IDs).

### GET/POST /commentaires/articles/ — `CommentaireArticleViewSet` (`ListCreateAPIView`)

- **Permission** : `EstAuteurOuModerateurOuLectureSeule` (lecture libre, écriture authentifiée).
- **Description** : GET liste les commentaires racines visibles (`?article=<id>` filtre) ; POST crée (`user` assigné auto).
- **Serializer** : `CommentaireArticleSerializer`
- **Entrée (POST)** : `article` (id), `parent` (id, optionnel — doit être une racine du même article), `contenu`.
- **Sortie** : `id` (read-only), `user` (read-only), `user_nom` (read-only), `article`, `parent`, `contenu`, `est_visible` (read-only), `est_modifie` (read-only), `nb_likes` (read-only), `est_like_par_moi` (read-only), `reponses` (read-only, récursif 1 niveau), `created_at`/`updated_at` (read-only).

### GET/PATCH/DELETE /commentaires/articles/\<pk\>/ — `CommentaireArticleDetail`

- **Permission** : `EstAuteurOuModerateurOuLectureSeule` (modif/suppr réservées à l'auteur, admin/staff, ou partenaire propriétaire de la cible).
- PATCH force `est_modifie=True`. Mêmes champs que ci-dessus.

### GET/POST /commentaires/partenaires/ — `CommentairePartenaireViewSet`

Identique au bloc articles, avec `?partenaire=<id>` comme filtre. **Sortie (`CommentairePartenaireSerializer`)** : `id`, `user`, `user_nom`, `partenaire`, `parent`, `contenu`, `est_visible`, `est_modifie`, `nb_likes`, `est_like_par_moi`, `reponses`, `created_at`, `updated_at` (mêmes read_only que ci-dessus).

### GET/PATCH/DELETE /commentaires/partenaires/\<pk\>/ — `CommentairePartenaireDetail`

Même logique que `CommentaireArticleDetail`.

### POST /commentaires/\<str:type_comm\>/\<pk\>/like/ — `ToggleLikeCommentaire`

- **Permission** : `IsAuthenticated`
- **Description** : Bascule le like sur un commentaire. `type_comm` ∈ `article`|`partenaire`, sinon `400 {"erreur": true, "message": "Type invalide."}`.
- **Sortie** : `{"actif": bool, "total": int}` (`nb_likes` du commentaire). Seul `POST` implémenté (DELETE → 405).

---

## App orders — /api/v1/orders/

### GET /paniers/ — `MesPaniersView`

- **Permission** : `IsAuthenticated`
- **Description** : Liste tous les paniers du client (un panier par couple partenaire + catégorie).
- **Sortie** (`PanierSerializer`) : `id` (read_only), `partenaire`, `partenaire_nom` (read_only), `categorie`, `categorie_nom` (read_only), `lignes` (read_only, liste `LignePanierSerializer`), `total` (read_only, calculé), `created_at`/`updated_at` (read_only).
  - `LignePanierSerializer` : `id` (read_only), `article`, `article_nom` (read_only), `variante_id`, `supplements` (JSON snapshot), `quantite`, `prix_unitaire` (read_only, figé), `prix_ligne` (read_only, calculé), `note_speciale`, `created_at` (read_only).

### POST /paniers/ajouter/ — `AjouterLigneView`

- **Permission** : `IsAuthenticated`
- **Description** : Ajoute un article au panier (crée le panier si besoin).
- **Entrée** (brut, `request.data`) : `article` (id, requis, `est_actif=True`), `quantite` (entier, défaut `1`, ≥1), `variante_id` (optionnel), `supplement_ids` (optionnel, liste d'ids), `note_speciale` (optionnel). Prix calculé serveur (`prix_promotion` si en promo, sinon `prix`, + supplément variante).
- **Sortie** : `PanierSerializer` mis à jour, statut `201`.

### POST /paniers/\<id\>/valider/ — `ValiderPanierView`

- **Permission** : `IsAuthenticated`
- **Description** : Transforme un panier en `Commande`, supprime le panier.
- **Entrée** : `mode_livraison` (optionnel, défaut `emporter` ; `emporter`|`sur_place`|`livraison`), `latitude`/`longitude` (**obligatoires si `livraison`**), `adresse` (optionnel, id `AdresseClient`), `heure_souhaitee` (optionnel), `mode_paiement` (optionnel, défaut `cash` ; `cash`|`mobile_money`), `notes_client` (optionnel), `frais_livraison` (optionnel, défaut `0`).
- **Sortie** : `CommandeSerializer` (voir plus bas), statut `201`. Erreur `400` si panier vide ou position GPS manquante pour livraison.

### DELETE /paniers/\<id\>/ — `ViderPanierView`

- **Permission** : `IsAuthenticated`
- **Sortie** : `{"message": "Panier vidé."}` (200). Seule méthode `delete` implémentée.

### PATCH/DELETE /lignes/\<id\>/ — `LigneDetailView`

- **Permission** : `IsAuthenticated` (pas de méthode GET définie — 405 si tenté)
- **PATCH — Entrée** : `quantite` (optionnel, ≥1), `note_speciale` (optionnel). **Sortie** : `PanierSerializer` parent.
- **DELETE — Sortie** : `{"message": "Panier vide et supprimé."}` si le panier devient vide, sinon `PanierSerializer` restant.

### GET /commandes/ — `MesCommandesClientView`

- **Permission** : `IsAuthenticated`
- **Entrée (query)** : `statut` (optionnel).
- **Sortie** : liste `CommandeSerializer`.

### GET /commandes/partenaire/ — `CommandesPartenaireView`

- **Permission** : `IsAuthenticated` (+ `profil_partenaire` requis, sinon 403)
- **Entrée (query)** : `statut` (optionnel).
- **Sortie** : liste `CommandeSerializer`.

### GET /commandes/\<id\>/ — `CommandeDetailView`

- **Permission** : `IsAuthenticated` (+ client propriétaire ou partenaire concerné, sinon 403)
- **Sortie** : `CommandeSerializer`.

**`CommandeSerializer`** (commun) : `id` (read_only), `numero` (read_only, format `PFR-<année>-<5 chiffres>`), `user` (read_only), `client_nom` (read_only), `client_telephone` (read_only), `partenaire` (read_only), `partenaire_nom` (read_only), `mode_livraison`, `adresse`, `adresse_snapshot`, `heure_souhaitee`, `statut` (read_only), `raison_refus`, `sous_total` (read_only), `frais_livraison`, `total` (read_only), `mode_paiement`, `notes_client`, `notes_partenaire`, `lignes` (read_only, liste `LigneCommandeSerializer`), `created_at`/`acceptee_le`/`prete_le`/`livree_le` (read_only).
`read_only_fields` explicites : `numero`, `user`, `partenaire`, `statut`, `sous_total`, `total`.
`LigneCommandeSerializer` (read-only) : `id`, `article` (nullable), `nom_article`, `variante_nom`, `supplements`, `quantite`, `prix_unitaire`, `prix_ligne`, `note_speciale`.

### POST /commandes/\<id\>/transition/ — `TransitionCommandeView`

- **Permission** : `IsAuthenticated` (+ client propriétaire ou partenaire concerné)
- **Entrée** : `statut` (requis, cible), `raison_refus` (optionnel, si `statut=refusee`).
- **Table des transitions** :

| Statut actuel | Cibles possibles |
|---|---|
| `nouvelle` | `acceptee`, `refusee`, `annulee` |
| `acceptee` | `en_preparation`, `annulee` |
| `en_preparation` | `prete`, `annulee` |
| `prete` | `en_livraison`, `livree`, `expiree` |
| `en_livraison` | `livree` |
| `livree`, `refusee`, `annulee`, `expiree` | *(final)* |

- Le **client** ne peut faire que `nouvelle → annulee` (403 sinon). Le **partenaire** peut faire toute transition listée.
- Effets de bord : `acceptee_le`/`prete_le`/`livree_le` posés selon la cible ; `raison_refus` si `refusee` ; `annulee_par` si `annulee`. Notification push envoyée.
- **Sortie** : `CommandeSerializer` mis à jour, statut `200`.

### POST /commandes/\<id\>/livreur/ — `CommanderLivreurView`

- **Permission** : `IsAuthenticated` (+ seul le partenaire propriétaire, sinon 403)
- **Description** : Déclenche une course de livraison (module `livraison`) pour une commande prête en mode livraison, passe la commande à `en_livraison`.
- **Entrée** : aucun body requis.
- **Erreurs** : `403` si pas propriétaire ; `400` si pas en mode livraison ou pas `prete` ou pas de position GPS partenaire ; `409` si une course est déjà en cours.
- **Sortie** (`201`) : `{"course": {"numero":..., "statut":..., "prix":...}, "commande_statut": "en_livraison", ...champs de finaliser_assignation}`.

**Récap valeurs de modèle** : `Commande.Statut` : `nouvelle, acceptee, refusee, en_preparation, prete, en_livraison, livree, annulee, expiree`. `ModeLivraison` : `emporter, sur_place, livraison`. `ModePaiement` : `cash, mobile_money`.

---

## App messaging — /api/v1/messaging/

### GET/POST /interventions/ — `DemandesView`

- **Permission** : `IsAuthenticated`
- **GET — query** : `statut` (optionnel).
- **POST — Entrée** (`request.data`, pas de serializer de validation) : `artisan` (id `ProfilPartenaire`, requis), `adresse` (id `AdresseClient`, optionnel), `type_intervention` (défaut `reparation`), `type_libre` (défaut `''`), `description` (défaut `''`), `urgence` (défaut `flexible`), `description_acces` (défaut `''`), `disponibilite_preferee` (défaut `indifferent`), `latitude`/`longitude` (optionnels).
- **Sortie** (`DemandeInterventionSerializer`) : `id`, `numero` (read_only), `user` (read_only), `client_nom` (calculé), `artisan`, `artisan_nom` (calculé), `client_telephone` (calculé), `artisan_telephone` (calculé), `type_intervention`, `type_libre`, `description`, `urgence`, `latitude`, `longitude`, `adresse`, `adresse_snapshot`, `description_acces`, `disponibilite_preferee`, `statut` (read_only), `date_proposee` (read_only), `prix_propose` (read_only), `raison_refus` (read_only), `conversation` (read_only), `photos` (read_only, liste), `created_at`.

### GET /interventions/artisan/ — `DemandesArtisanView`

- **Permission** : `IsAuthenticated` (+ `profil_partenaire` requis, sinon 403)
- **Query** : `statut` (optionnel).
- **Sortie** : liste `DemandeInterventionSerializer`.

### GET /interventions/\<int:pk\>/ — `DemandeDetailView`

- **Permission** : `IsAuthenticated` (+ client propriétaire ou artisan concerné, sinon 403)
- Seule la méthode `GET` est implémentée (pas de PATCH/DELETE malgré la route générique).

### POST /interventions/\<int:pk\>/transition/ — `TransitionDemandeView`

- **Permission** : `IsAuthenticated` (+ client ou artisan de la demande)
- **Table des transitions** : `en_attente → acceptee|refusee|annulee`, `acceptee → en_cours|annulee`, `en_cours → terminee|annulee`, `terminee`/`refusee`/`annulee` = finaux.
- Le client ne peut faire que `annulee` (403 sinon).
- **Entrée** : `statut` (requis), `date_proposee`/`prix_propose` (si `acceptee`), `raison_refus` (si `refusee`).
- **Sortie** : `DemandeInterventionSerializer` mis à jour.

### POST /interventions/\<int:pk\>/photos/ — `AjouterPhotoView`

- **Permission** : `IsAuthenticated` (demande doit appartenir au client, sinon 404)
- **Entrée** (`DemandeInterventionPhotoSerializer`) : `image` (requis), `legende` (optionnel), `ordre` (optionnel). `demande` injecté depuis l'URL.
- **Sortie** : `id`, `demande`, `image`, `legende`, `ordre`, `created_at` (read_only). Statut `201`.

### POST /contacter/ — `ContacterView`

- **Permission** : `IsAuthenticated`
- **Entrée** : `article` (id `Article` actif, optionnel) ou `partenaire` (id `ProfilPartenaire` `statut=actif`, optionnel si `article` absent). 400 si ni l'un ni l'autre.
- **Sortie** : `ConversationSerializer` + `nouvelle` (bool). Statut `201` si nouvelle, `200` sinon.

### GET/POST /conversations/ — `ConversationsView`

- **Permission** : `IsAuthenticated`
- **GET** : conversations où l'utilisateur est client et/ou partenaire.
- **POST — Entrée** : `partenaire` (id, requis), `article` (optionnel).
- **Sortie** (`ConversationSerializer`) : `id`, `client` (read_only), `client_nom` (calculé), `partenaire`, `partenaire_nom` (calculé), `article`, `client_telephone` (calculé), `partenaire_telephone` (calculé), `derniere_activite`, `est_archivee`, `dernier_message` (calculé, objet `{contenu, created_at}` ou `null`), `created_at`. Statut `201` (toujours, même si déjà existante).

### GET /conversations/\<int:pk\>/messages/ — `MessagesView`

- **Permission** : `IsAuthenticated` (+ participant requis, sinon 403)
- Seule `GET` est implémentée — l'envoi de messages se fait via le WebSocket, pas via ce endpoint REST.
- **Sortie** (`MessageSerializer`, liste) : `id`, `conversation`, `expediteur` (read_only), `expediteur_nom` (calculé, `'Système'` si absent), `type`, `contenu`, `media_url`, `statut` (read_only), `created_at`.

### WebSocket

`apps/messaging/consumers.py` (`ChatConsumer`) + `routing.py` : `ws/chat/<conversation_id>/` (Django Channels), hors périmètre REST.

---

## App livreurs — /api/v1/livreurs/

Pas de `serializers.py` — sérialisation par dicts manuels.

### POST /position/ — `MaPositionView`

- **Permission** : `IsAuthenticated`
- **Description** : Le livreur envoie sa position GPS (via `SourceTelephone`).
- **Entrée** : `latitude` (requis), `longitude` (requis).
- **Sortie** : `200 {"message": "Position enregistree."}` ; `403 {"erreur": true, "message": "Reserve aux livreurs."}` si pas de `profil_livreur` ; `400` si champs manquants/invalides. Seul `POST` implémenté.

### POST /position-transpondeur/ — `PositionTranspondeurView`

- **Permission** : `AllowAny` (identifié par `transpondeur_id`, non sécurisé par token device — à noter)
- **Description** : Un boîtier transpondeur envoie la position d'un livreur (via `SourceTranspondeur`).
- **Entrée** : `transpondeur_id` (requis), `latitude` (requis), `longitude` (requis).
- **Sortie** : `200 {"message": "Position enregistree."}` ; `400` si champs manquants/invalides ; `404 {"erreur": true, "message": "Transpondeur inconnu."}`.

### POST /statut/ — `MonStatutView`

- **Permission** : `IsAuthenticated`
- **Description** : Le livreur passe en ligne/hors ligne.
- **Entrée** : `statut` (requis, `Livreur.Statut.EN_LIGNE` ou `HORS_LIGNE`).
- **Sortie** : `200 {"message": "Statut: <valeur>."}` ; `403` si pas livreur ; `400` si statut invalide. Seul `POST` implémenté.

### GET /proches/ — `LivreursProchesView`

- **Permission** : `IsAuthenticated`
- **Description** : Livreurs EN_LIGNE (filtrés par ville/département du demandeur si connu), triés par distance, limités à 50.
- **Entrée (query)** : `lat` (optionnel), `lng` (optionnel).
- **Sortie** (liste, dict manuel) : `id` (uuid str), `nom`, `type_vehicule`, `latitude`/`longitude` (float ou null), `position_maj_le` (isoformat ou null).

---

## App livraison — /api/v1/livraison/

Pas de `serializers.py` : sérialisation manuelle via `_course_dict(c)` (dans `views.py`). Entrée lue directement via `request.data.get(...)`.

### Structure de sortie commune : `_course_dict(c)`

```json
{
  "id": "uuid",
  "numero": "LIV-2026-00001",
  "statut": "demandee|assignee|acceptee|vers_a|colis_pris|vers_b|livree|refusee|annulee",
  "ville": "nom du departement",
  "description_colis": "string",
  "prix": 0,
  "point_a": {"quartier":"","nom_contact":"","telephone_contact":"","gps":{"latitude":0.0,"longitude":0.0}},
  "point_b": {"quartier":"","nom_contact":"","telephone_contact":"","gps":{"latitude":0.0,"longitude":0.0}},
  "livreur": "uuid ou null",
  "livreur_position": {"latitude":0.0,"longitude":0.0,"type_vehicule":"","maj_le":"iso ou null"},
  "position_b_deposee": true,
  "cree_le": "iso datetime"
}
```
`livreur_position` = dernière position connue du livreur (pas liée à la course). `contact_user` (destinataire) n'est **jamais** exposé (confidentialité).

### GET /tarif/ — `TarifView`

- **Permission** : `AllowAny`
- **Sortie** : `{"prix_course": 500}` (piloté par `ParametresLivraison`, singleton admin).

### GET /icones-motard/ — `IconesMotardView`

- **Permission** : `AllowAny`
- **Sortie** : `{"standard": "url ou null", "terminee": "url ou null"}`.

### GET /courses/ — `MesCoursesView`

- **Permission** : `IsAuthenticated`
- **Query** : `statut` (optionnel). Limité à 100 résultats.
- **Sortie** : liste de `_course_dict`.

### POST /courses/creer/ — `CreerCourseView`

- **Permission** : `IsAuthenticated`
- **Description** : Crée une course A→B, tente l'assignation automatique (livreur EN_LIGNE le plus proche, même ville, PostGIS).
- **Entrée** — requis : `ville` (id Departement), `a_quartier`, `a_nom_contact`, `a_telephone_contact`, `b_quartier`, `b_nom_contact`, `b_telephone_contact`. Optionnels : `a_latitude`/`a_longitude`, `b_latitude`/`b_longitude`, `description_colis` (défaut `''`), `prix` (défaut `0`). `type_demandeur` déduit côté serveur (non fourni par le client).
- **Effets de bord** : lookup asynchrone du destinataire (`programmer_lookup_destinataire`), assignation auto (`finaliser_assignation`).
- **Sortie** (`201`) : `{"course": {...}, "assigne": true|false, "message"?: "..."}`. `400 {"erreur": true, "message": "Champs requis: <liste>."}` si champs manquants.

### GET /courses/recues/ — `CoursesRecuesView`

- **Permission** : `IsAuthenticated`
- **Description** : Courses où l'utilisateur est le destinataire (`contact_user`, lié via lookup automatique).
- **Query** : `statut` (optionnel). Limité à 100.
- **Sortie** : liste de `_course_dict`.

### GET /courses/\<uuid:pk\>/ — `CourseDetailView`

- **Permission** : `IsAuthenticated` (+ demandeur, livreur assigné, ou destinataire lié uniquement)
- **Sortie** : `_course_dict` + `je_suis_livreur` (bool), `je_suis_destinataire` (bool). `403 {"erreur": true, "message": "Acces refuse."}` sinon.

### POST /courses/\<uuid:pk\>/position-contact/ — `PositionContactView`

- **Permission** : `IsAuthenticated` (+ seul le destinataire lié, `contact_user_id`)
- **Entrée** : `latitude`, `longitude` (requis).
- **Sortie** : `_course_dict` mis à jour. `403` si pas destinataire ; `400` si coordonnées manquantes/invalides. Seul `POST` implémenté.

### POST /courses/\<uuid:pk\>/transition/ — `TransitionCourseView`

- **Permission** : `IsAuthenticated` (+ demandeur ou livreur assigné)
- **Statuts** (`Course.Statut`) : `demandee, assignee, acceptee, vers_a, colis_pris, vers_b, livree, refusee, annulee`.
- **Table des transitions** :

| Statut courant | Cibles |
|---|---|
| `demandee` | `assignee`, `annulee` |
| `assignee` | `acceptee`, `refusee`, `annulee` |
| `acceptee` | `vers_a`, `annulee` |
| `vers_a` | `colis_pris`, `annulee` |
| `colis_pris` | `vers_b` |
| `vers_b` | `livree` |
| `refusee` | `assignee` |
| `livree`, `annulee` | *(final)* |

- Le **livreur** peut toute transition listée. Le **demandeur** ne peut faire que `annulee`, et seulement si statut ∈ `[demandee, assignee, acceptee, vers_a]`.
- **Entrée** : `statut` (requis, cible), `raison_refus` (optionnel, si cible=`refusee`).
- Effets de bord : `acceptee_le`/`colis_pris_le`/`livree_le`/`annulee_le` posés ; si `livree` et `commande_id` renseigné, met à jour `Commande.statut=LIVREE` liée. Notifications FCM envoyées selon la matrice statut→destinataires.
- **Sortie** : `_course_dict` mis à jour. `403`/`400` selon les cas décrits ci-dessus.

### WebSocket

`ws://<host>/ws/course/<course_id>/position/?token=<access>` (`PositionCourseConsumer`). Rôles : `livreur` (émet), `demandeur`/`destinataire` (reçoivent). Refus 4001 (non authentifié) / 4003 (non partie à la course).

---

## App payments — /api/v1/payments/

Le module est protégé par le flag waffle `paiement_actif` : si inactif, toutes les vues renvoient `503 {"erreur": true, "message": "Module paiement désactivé."}`.

### GET/POST /paiements/ — `PaiementsView`

- **Permission** : `IsAuthenticated`
- **GET** : admin (`is_staff`/`role=ADMIN`) voit tous les paiements ; sinon seulement les siens. Query : `statut` (optionnel).
- **POST — Entrée** (`PaiementSerializer`, hors read_only) : `partenaire`, `type_objet`, `objet_id`, `montant`, `mode`, `reference_externe`, `note`. `user` et `statut` (forcé `en_attente`) posés côté serveur.
- **Sortie** : `PaiementSerializer` — champs : `id`, `user`, `partenaire`, `type_objet`, `objet_id`, `montant`, `mode`, `statut`, `reference_externe`, `note`, `valide_par`, `valide_le`, `cree_le`, `modifie_le`. `read_only_fields` : `user`, `statut`, `valide_par`, `valide_le`. Statut `201` sur POST.

### POST /paiements/\<uuid:pk\>/valider/ — `ValiderPaiementView`

- **Permission** : `IsAuthenticated` (+ vérification manuelle admin : `is_staff` ou `role=ADMIN`, sinon `403`)
- **Entrée** : `statut` (requis, `CONFIRME`|`REJETE`|`REMBOURSE`), `note` (optionnel).
- **Sortie** : `PaiementSerializer` mis à jour. `404` si introuvable, `400` si statut cible invalide.

---

## App notifications — /api/v1/notifications/

Pas de `serializers.py`.

### POST /token/ — `EnregistrerTokenFCMView`

- **Permission** : `IsAuthenticated`
- **Description** : L'app mobile enregistre son token FCM (stocké même si le flag `fcm_actif` est off).
- **Entrée** : `token_fcm` (requis).
- **Sortie** : `200 {"message": "Token FCM enregistré."}` ; `400 {"erreur": true, "message": "token_fcm requis."}` si vide.

### DELETE /token/ — `EnregistrerTokenFCMView` (méthode `delete`)

Bien que `urls.py` ne déclare qu'une route pour `POST`, la classe définit aussi `delete` — **DELETE sur la même URL `/api/v1/notifications/token/` fonctionne**.

- **Permission** : `IsAuthenticated`
- **Description** : Désenregistre le token FCM (déconnexion/désactivation).
- **Sortie** : `200 {"message": "Token FCM supprimé."}`.

---

## App analytics — /api/v1/analytics/

Pas de `serializers.py` — `APIView` avec `request.data` brut et `Response` construites à la main, sans validation de schéma DRF.

Plusieurs endpoints sont protégés par le flag waffle `analytics_actif` (`403 {'detail': 'Analytics désactivé.'}` sinon — message sans accent pour `livraison/vue/`) : cela concerne uniquement les endpoints d'écriture d'événements (session, catégorie, vitrine, livraison/vue, intervention), **pas** les endpoints admin/lecture.

Les endpoints admin utilisent `IsAuthenticated` + vérification manuelle `is_staff` dans le code (pas `IsAdminUser` DRF), message `{'detail': 'Réservé aux administrateurs.'}`.

### POST /session/demarrer/ — `DemarrerSessionView`

- **Permission** : `IsAuthenticated` + flag requis
- **Entrée** : `source` (optionnel, `mobile`|`web`, défaut `mobile`)
- **Sortie** (`201`) : `{"session_id": "uuid"}`

### POST /session/ping/ — `PingSessionView`

- **Permission** : `IsAuthenticated` + flag requis
- **Entrée** : `session_id` (requis, uuid, doit appartenir à l'utilisateur et être active)
- **Sortie** : `{"duree_secondes": int, "minute_session": int}`. `404 {'detail': 'Session introuvable.'}` sinon. Delta borné entre 0 et 300s.

### POST /categorie/visite/ — `VisiteCategorieView`

- **Permission** : `IsAuthenticated` + flag requis
- **Entrée** : `categorie` (slug, prioritaire) ou `categorie_id` (fallback, résolu en slug).
- **Sortie** (`201`) : `{"message": "Visite enregistrée."}`. `400 {"erreur": true, "message": "Catégorie manquante."}` sinon.

### POST /vitrine/vue/ — `VueVitrineView`

- **Permission** : `AllowAny` + flag requis
- **Entrée** : `partenaire` (requis, id), `source` (optionnel, `annuaire|recherche|article|favoris|publicite|autre`, défaut `autre`), `avec_catalogue` (optionnel, bool, défaut `True`).
- **Sortie** (`201`) : `{"message": "Vue enregistrée."}`. `400` si `partenaire` manquant, `404` si introuvable.

### POST /livraison/vue/ — `VueServiceLivraisonView`

- **Permission** : `AllowAny` + flag requis
- **Entrée** : `source` (optionnel, `onglet`|`autre`, défaut `onglet`)
- **Sortie** (`201`) : `{"message": "Vue enregistree."}` (sans accent).

### GET /livraison/client/\<int:user_id\>/ — `LivraisonStatsClientView`

- **Permission** : `IsAuthenticated` + `is_staff`
- **Sortie** : `{"nb_consultations": int, "nb_utilisations_demandeur": int, "nb_utilisations_destinataire": int}`. Pas de 404 si `user_id` inexistant (renvoie des 0).

### GET /livraison/partenaire/\<int:partenaire_id\>/ — `LivraisonStatsPartenaireView`

- **Permission** : `IsAuthenticated` + `is_staff`
- **Sortie** : `{"nb_livreurs_commandes": int}` — ⚠️ nom trompeur, il s'agit en réalité d'un nombre de **courses**, pas de livreurs. Pas de 404 si partenaire inexistant.

### GET /livraison/tableau-de-bord/ — `LivraisonTableauDeBordView`

- **Permission** : `IsAuthenticated` + `is_staff`
- **Query** : `debut`, `fin` (format `YYYY-MM-DD`, optionnels ; `400` si format invalide)
- **Sortie** : objet avec `genere_le`, `periode`, `taux_conversion` (`nb_consultations`, `nb_courses`, `ratio_courses_par_consultation`), `ca_total` (somme `Course.prix` pour statut `LIVREE`), `ca_par_periode` (`par_jour`, `par_mois`, `par_heure`), `repartition_demandeurs`, `top_villes` (top 10), `top_quartiers_depart` (top 10), `top_categories_partenaire` (top 10).

### GET /livraison/tableau-de-bord/export/ — `LivraisonTableauDeBordExportView`

- **Permission** : `IsAuthenticated` + `is_staff`
- **Query** : `debut`/`fin` (mêmes règles)
- **Sortie** : CSV (`section;cle;valeur`) — mêmes données que l'endpoint précédent, à plat.

### POST /intervention/ouverture/ — `OuvertureDemandeInterventionView`

- **Permission** : `IsAuthenticated` + flag requis
- **Entrée** : aucun champ lu.
- **Sortie attendue** : `201 {"message": "Ouverture enregistrée."}`.
- ⚠️ **Anomalie détectée** : la vue appelle `enregistrer_demande_intervention(request.user)` importée depuis `.services`, mais cette fonction **n'existe pas** dans `apps/analytics/services.py` (vérifié, fichier lu en entier) ni ailleurs dans le projet. Cet endpoint provoquera vraisemblablement une erreur serveur (500) en l'état — à signaler au backend avant intégration front.

### GET /admin/engagement/ — `EngagementAdminView`

- **Permission** : `IsAuthenticated` + `is_staff`
- **Sortie** : `{"nb_profils": int, "nb_clients_actifs": int, "profils": [{"utilisateur_id","telephone","username","nb_articles_vus_mois","nb_vues_catalogue_mois","temps_cumule_secondes_mois","derniere_activite","est_client_actif","categories_consultees": {slug: count}}]}`. Non paginé.

### GET /admin/stats-connexion/ — `StatsConnexionAdminView`

- **Permission** : `IsAuthenticated` + `is_staff`
- **Sortie** : `{"genere_le", "en_ligne": {"total","par_role"}, "comptes": {"total","par_role"}, "connexions_distinctes": {"aujourdhui","sept_jours","trente_jours"}, "ouvertures": {"aujourdhui","sept_jours","trente_jours" (chacun {"total","personnes","moyenne_par_personne"})}}`. `par_role` = dict fixe `{client, partenaire, livreur, admin}`.

### GET /admin/stats-connexion/export/ — `StatsConnexionExportView`

- **Permission** : `IsAuthenticated` + `is_staff`
- **Query** : `jours` (optionnel, int ; invalide → ignoré silencieusement, pas de 400)
- **Sortie** : CSV, colonnes `id;utilisateur;role;source;debut;dernier_ping;duree_secondes;active`.

**Anomalies à signaler** : (1) `/intervention/ouverture/` cassé (fonction manquante) ; (2) `nb_livreurs_commandes` mal nommé ; (3) `livraison/client` et `livraison/partenaire` ne renvoient jamais 404 ; (4) message de flag désactivé incohérent avec/sans accent selon l'endpoint.

---

## App publicites — /api/v1/publicites/

### GET /formules/ — `FormulesView`

- **Permission** : `IsAuthenticated`
- **Sortie** : liste `FormulePubliciteSerializer` — `id` (read_only), `nom`, `prix`, `priorite`, `duree_jours`, `passages_par_jour`, `duree_affichage_secondes`, `quota_partenaires`, `acces_heures_affluence`, `types_affichage` (liste parmi `carrousel|interstitiel|bandeau_bas|page_publicites`), `nb_images_max`, `video_autorisee`, `duree_video_max_secondes`, `cible_pourcentage_actifs`.

### GET /mes-stats/ — `StatsPartenaireView`

- **Permission** : `IsAuthenticated` (+ `profil_partenaire` requis, sinon 403)
- **Sortie** : `{"publicites": [...]}` — si `stats_visibles_partenaire=True` : `id`, `titre`, `formule`, `statut`, `nb_personnes_touchees`, `nb_impressions`, `nb_clics`, `taux_clic` (%, 2 décimales), `impressions_par_type`, `cible_pourcentage`, `cible_atteinte`, `debut_diffusion`, `fin_diffusion`. Sinon : `id`, `titre`, `formule`, `statut`, `stats_disponibles: false`, `message`.

### GET /admin/stats/ — `StatsAdminView`

- **Permission** : `IsAuthenticated` (+ `is_staff` requis)
- **Sortie** : `{"totaux": {"nb_publicites","nb_actives","total_impressions","total_personnes_touchees","total_clics"}, "publicites": [...]}` (format complet, sans filtre de visibilité).

### GET /admin/export/ — `ExportCSVView`

- **Permission** : `IsAuthenticated` (+ `is_staff` requis)
- **Query** : `type` = `publicites` (défaut) | `impressions` | `profils` | `sessions`. `400` si type invalide.
- **Sortie** : CSV téléchargeable, colonnes variables selon `type` (voir détail par type dans le rapport source).

### GET /carrousel/ — `CarrouselView`

- **Permission** : `AllowAny`
- **Sortie** : `{"publicites": [PubliciteListSerializer]}` — `id`, `titre`, `image_couverture`, `partenaire_id` (read_only), `duree_affichage_secondes` (read_only), `priorite` (read_only). `{"publicites": []}` si flag `publicite_active` inactif.

### GET / — `PagePublicitesView` (liste)

- **Permission** : `AllowAny`
- **Sortie** : `{"publicites": [PubliciteListSerializer]}` (mêmes champs que carrousel).

### GET /interstitiel/ — `InterstitielView`

- **Permission** : `IsAuthenticated`
- **Query** : `minute_session` (optionnel, int)
- **Sortie** : `{"publicite": PubliciteDetailSerializer | null}` — `id`, `titre`, `description`, `image_couverture`, `video`, `images` (liste `{id,image,ordre}`), `partenaire_id` (read_only), `nom_partenaire` (read_only), `portee` (`departement|region|district`), `portee_effective` (read_only).

### GET /bandeau-bas/ — `BandeauBasView`

- **Permission** : `AllowAny`
- **Sortie** : `{"publicite": PubliciteListSerializer | null}`.

### GET/POST /mes-publicites/ — `MesPublicitesView`

- **Permission** : `IsAuthenticated`
- **GET** : publicités du partenaire connecté (`-cree_le`).
- **POST — Entrée** (`PubliciteCreationSerializer`) : `formule` (id, requis), `titre` (requis), `description` (optionnel), `image_couverture` (fichier, requis), `video` (fichier, optionnel), `portee` (optionnel, défaut `departement`).
- **Sortie** : `id` (read_only), `formule`, `titre`, `description`, `image_couverture`, `video`, `portee`, `statut` (read_only, forcé `brouillon`).
- Validations : formule doit être active, vidéo interdite si formule ne l'autorise pas, portée doit être ≥ celle du forfait.

### GET /\<id\>/ — `PubliciteDetailView`

- **Permission** : `AllowAny`
- **Sortie** : `PubliciteDetailSerializer` (voir interstitiel). Restreint à `statut=active`.

### POST /\<id\>/impression/ — `EnregistrerImpressionView`

- **Permission** : `AllowAny`
- **Entrée** : `cliquee` (optionnel, bool, défaut `false`), `type_affichage` (optionnel, défaut `carrousel`), `minute_session` (optionnel), `session_id` (optionnel, dédup).
- **Sortie** : `201 {"message": "Impression enregistrée."}` ou `200` si déjà comptée. `404` si pub introuvable/inactive.

### POST /\<id\>/transition/\<action\>/ — `TransitionPubliciteView`

- **Permission** : `IsAuthenticated` (+ actions admin réservées à `is_staff`)
- **Actions** :

| action | depuis | vers | admin | 
|---|---|---|---|
| `soumettre` | `brouillon` | `en_attente_paiement` | non |
| `confirmer_paiement` | `en_attente_paiement` | `en_attente_validation` (ou `active` si validation auto) | oui |
| `valider` | `en_attente_validation` | `active` | oui |
| `rejeter` | `en_attente_validation`, `en_attente_paiement` | `rejetee` | oui |
| `terminer` | `active` | `terminee` | oui |

- **Sortie** : `200 {"statut": "...", "message": "..."}`. Erreurs : `400` action inconnue/transition impossible, `403` réservé admin, `404` publicité introuvable, `409` quota de formule atteint.

---

## App geo — /api/v1/geo/

### GET /departements/ — `DepartementsView`

- **Permission** : `AllowAny`
- **Pagination** : désactivée
- **Sortie** (`DepartementSerializer`) : `id`, `nom`, `region` (read_only, `source=region.nom`), `district` (read_only, `source=region.district.nom`). Triés `region__district__ordre`, `region__ordre`, `ordre`, `nom`.

### GET /quartiers/ — `QuartiersView`

- **Permission** : `AllowAny`
- **Pagination** : désactivée
- **Query** : `departement` (optionnel, filtre `departement_id`)
- **Sortie** (`QuartierSerializer`) : `id`, `nom`. Triés `ordre`, `nom`.

---

## App version — /api/v1/version/

### GET /verifier/ — `VerifierVersionView`

- **Permission** : `AllowAny`
- **Query** : `version` (optionnel, défaut `''`), `plateforme` (optionnel, défaut `android`).
- **Description** : Compare la version cliente à `ControleVersion.obtenir()` (singleton).
- **Sortie** (dict manuel, pas de serializer) :
```json
{
  "statut": "a_jour | conseillee | obligatoire",
  "obligatoire": true,
  "lien_store": "url",
  "message": "",
  "version_min_obligatoire": "1.0.0",
  "version_conseillee": "1.0.0"
}
```
Seul `GET` implémenté.

---

## App administration — /api/v1/administration/

Toutes les routes exigent `IsAuthenticated` + une capacité de la grille `PermissionsAdmin` via `ADroitDe('<capacité>')`, ou `EstSuperAdmin`. `ADroitDe` autorise si `is_superuser=True`, sinon exige `is_staff=True` **et** toutes les capacités listées cochées sur `user.permissions_admin`.

### GET /dashboard/ — `DashboardG5View`

- **Permission** : `ADroitDe('voir_stats')`
- **Description** : Stats de connexion (réexposées depuis `analytics.stats_connexion`) + répartition appareils + comptes par statut.
- **Sortie** : mêmes champs que `StatsConnexionAdminView` (analytics) + `appareils` (`{"total","appareils_distincts","par_plateforme"}`, sessions actives uniquement) + `comptes_par_statut` (`{"total","actifs","suspendus","bannis","supprimes"}`).

### GET /appareils/export/ — `AppareilsExportView`

- **Permission** : `ADroitDe('exporter_csv')`
- **Query** : `actives` (`1` par défaut = actives seulement, `0` = tout l'historique).
- **Sortie** : CSV `id, utilisateur, role, plateforme, appareil_nom, appareil_id, adresse_ip, derniere_activite, active`.

### POST /moderation/ — `ModerationView`

- **Permission** : `EstSuperAdmin` (**seule vue à ne pas utiliser `ADroitDe`**)
- **Entrée** : `{"cible_id": int, "action": "suspendre|reactiver|bannir|supprimer_soft|supprimer_hard|restaurer", "motif": "..."}`. Garde-fou : auto-modération interdite.
- **Sortie** : `200 {"detail": "Action effectuée.", "action": "..."}` ; `400`/`404` selon erreurs. `supprimer_hard` est **irréversible**.

### GET /moderation/journal/ — `JournalModerationView`

- **Permission** : `ADroitDe('lire_journal')`
- **Sortie** : `{"total": int, "entrees": [{"date","action","action_libelle","acteur","cible","cible_role","motif"}]}` (200 entrées les plus récentes max).

### GET /moderation/journal/export/ — `JournalExportView`

- **Permission** : `ADroitDe('lire_journal', 'exporter_csv')` (les deux)
- **Sortie** : CSV complet `date, action, acteur, cible, cible_role, motif`.

### GET /partenaires/ — `IndicateursPartenairesView`

- **Permission** : `ADroitDe('voir_indicateurs')`
- **Sortie** : `{"total","par_plan","par_type","par_departement","par_statut","certifies","en_faveur","actifs","visibles","expirations": {"deja_expire","demain","sous_5j","sous_15j","sous_30j"}}` (tranches d'expiration exclusives).

### GET /partenaires/export/ — `PartenairesExportView`

- **Permission** : `ADroitDe('exporter_csv')`
- **Sortie** : CSV `nom_commerce, telephone, type, plan, departement, statut, abonnement_fin, certifie, faveur, visible, nb_vues`.

### POST/DELETE /partenaires/\<pk\>/faveur/ — `FaveurView`

- **Permission** : `ADroitDe('accorder_faveur')`
- **POST — Entrée** : `{"plan_code": "premium", "motif": "..."}`. **DELETE — Entrée** : `{"motif": "..."}` (optionnel, remet au plan `basique`).
- **Sortie** (200) : `MonProfilPartenaireSerializer` (voir app users).

### POST/DELETE /publicites/\<pk\>/faveur/ — `FaveurPubliciteView`

- **Permission** : `ADroitDe('offrir_campagne')`
- **POST — Entrée** : `{"motif": "..."}` (active la pub sans paiement). **DELETE — Entrée** : `{"motif": "..."}` (termine la pub offerte).
- **Sortie** (200, dict custom `_faveur_pub_reponse`) : `id`, `titre`, `statut`, `est_faveur`, `debut_diffusion`, `fin_diffusion`, `faveur_motif`.

### GET/POST /demandes-partenariat/ — `DemandesPartenariatView`

- **Permission** : `ADroitDe('valider_devenir_partenaire')`
- **GET — Sortie** : `{"total": int, "demandes": [{"id","nom_commerce","telephone","nom_complet","departement","type_partenaire","cree_le"}]}` (statut `en_attente`, triés par ancienneté).
- **POST — Entrée** : `{"partenaire_id": int, "decision": "accepter|rejeter", "motif": "..."}`.
- **Sortie POST** : `200 {"statut": "...", "id": int}`. `404` si demande introuvable/déjà traitée.

### Note hors périmètre

`apps/administration/dashboard_admin.py` (`vue_tableau_de_bord`) est une vue Django classique (HTML, pas DRF/JSON), montée hors `/api/v1/` à `/admin/tableau-de-bord/` — **pas consommable par Angular**, mentionnée pour information seulement.
