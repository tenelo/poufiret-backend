# API REST complète Poufiret

Référence générée depuis `poufiret_backend/urls.py` et les `urls.py`, vues et serializers des apps. Toutes les routes ci-dessous sont préfixées par `/api/v1/`.

## Conventions

- `RO` signifie read-only : renvoyé en sortie mais non modifiable par le serializer.
- `sortie manuelle` signifie que la vue construit directement le JSON ; aucun serializer n'est utilisé.
- Les paramètres `?` sont des query parameters, pas des champs du body.
- Les permissions indiquées sont celles déclarées par la vue. Certaines vues ajoutent ensuite un contrôle métier (propriétaire, partenaire, staff, rôle ou capacité).
- Le préfixe réel du catalogue est `/api/v1/catalogue/`, malgré le nom d'app Python `catalog`.

## Résumé des apps exposées

| App | Préfixe | Routes principales |
|---|---|---:|
| users/auth | `/api/v1/auth/` | 17 |
| catalog | `/api/v1/catalogue/` | routes explicites + 7 viewsets DRF |
| social | `/api/v1/social/` | 11 |
| orders | `/api/v1/orders/` | 10 |
| messaging | `/api/v1/messaging/` | 8 |
| livreurs | `/api/v1/livreurs/` | 4 |
| livraison | `/api/v1/livraison/` | 8 |
| payments | `/api/v1/payments/` | 2 |
| notifications | `/api/v1/notifications/` | 1 |
| analytics | `/api/v1/analytics/` | 13 |
| publicites | `/api/v1/publicites/` | 12 |
| geo | `/api/v1/geo/` | 2 |
| version | `/api/v1/version/` | 1 |
| administration | `/api/v1/administration/` | 10 |

# Auth / users

## `/api/v1/auth/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| POST | `/api/v1/auth/inscription/` | `InscriptionView` | `AllowAny` | `telephone`, `username`, `first_name`, `last_name`, `password` (PIN 4 chiffres), `departement?`, `tranche_age?`, `sexe?` | `access`, `refresh`, `utilisateur` (`UtilisateurSerializer`) : `id` RO, `telephone` RO, `username`, `first_name`, `last_name`, `role` RO, `est_verifie` RO, `pin_par_defaut` RO, `langue_preferee`, `token_fcm`, `departement`, `departement_nom` RO, `region_nom` RO, `tranche_age`, `sexe` |
| POST | `/api/v1/auth/connexion/` | `ConnexionView` | permission par défaut JWT | `telephone`, `password` ; `appareil_id?`, `appareil_nom?`, `plateforme?` sont utilisés pour tracer l'appareil | `access`, `refresh`, `utilisateur` avec les champs `UtilisateurSerializer` |
| POST | `/api/v1/auth/otp/demander/` | `DemanderOTPView` | `AllowAny` | `telephone`, `but` (`inscription` par défaut ou `reinit_pin`) | `deja_verifie`, `compte_existe`, `otp_envoye` |
| POST | `/api/v1/auth/otp/verifier/` | `VerifierOTPView` | `AllowAny` | `telephone`, `code`, `but` (`inscription` par défaut ou `reinit_pin`) | `verifie`, `message` |
| POST | `/api/v1/auth/pin/definir/` | `DefinirPINView` | `AllowAny` | `telephone`, `password` (PIN 4 chiffres), `but` (`inscription` par défaut ou `reinit_pin`), `username?`, `first_name?`, `last_name?` | `access`, `refresh`, `utilisateur` (`UtilisateurSerializer`) |
| POST | `/api/v1/auth/pin/changer/` | `ChangerPINView` | `IsAuthenticated` | `ancien_pin`, `nouveau_pin` (4 chiffres, write-only) | `access`, `refresh`, `utilisateur` (`UtilisateurSerializer`) |
| POST | `/api/v1/auth/rafraichir/` | `TokenRefreshView` | public JWT | `refresh` | `access` et, selon configuration SimpleJWT, `refresh` renouvelé |
| POST | `/api/v1/auth/deconnexion/` | `DeconnexionView` | `IsAuthenticated` | `refresh`; `appareil_id?` | `message` |
| GET, PATCH | `/api/v1/auth/moi/` | `MonProfilView` | `IsAuthenticated` | PATCH : `username`, `first_name`, `last_name`, `langue_preferee`, `token_fcm`, `departement`, `tranche_age`, `sexe`; `id`, `telephone`, `role`, `est_verifie`, `pin_par_defaut`, `departement_nom`, `region_nom` RO | `UtilisateurSerializer` : `id`, `telephone`, `role`, `est_verifie`, `pin_par_defaut`, `departement_nom`, `region_nom` RO |
| POST | `/api/v1/auth/devenir-partenaire/` | `DevenirPartenaireView` | `IsAuthenticated` | `type_partenaire`, `nom_commerce`, `description`, `adresse`, `quartier`, `secteur`, `ville`, `departement`, `telephone_pro`, `whatsapp`, `email_pro`, `categories?` (liste d'IDs) | `message`, `utilisateur` (`UtilisateurSerializer`) |
| POST | `/api/v1/auth/partenaires/creer/` | `CreerPartenaireParAdminView` | `IsAuthenticated` + `ADroitDe('creer_partenaire')` | `telephone`, `prenom?`, `nom?`, `type_partenaire`, `nom_commerce`, `description?`, `adresse?`, `quartier?`, `secteur?`, `ville?`, `departement?`, `telephone_pro?`, `whatsapp?`, `email_pro?`, `plan_id?`, `categories?[]` | serializer renvoyé avec le profil créé et le PIN aléatoire en clair une seule fois |
| GET, PATCH | `/api/v1/auth/mon-profil-partenaire/` | `MonProfilPartenaireView` | `IsAuthenticated`, partenaire requis | PATCH : `nom_commerce`, `description`, `logo`, `photo_couverture`, `type_partenaire`, `adresse`, `quartier`, `secteur`, `ville`, `description_acces`, `telephone_pro`, `whatsapp`, `email_pro`; autres champs RO | `MonProfilPartenaireSerializer` avec champs modifiables et champs calculés/libellés RO |
| GET | `/api/v1/auth/mes-categories/` | `MesCategoriesView` | `IsAuthenticated`, partenaire requis | aucun | liste `MaCategorieSerializer` : lien catégorie/partenaire et image de couverture selon le serializer |
| GET, PATCH | `/api/v1/auth/mes-categories/<int:pk>/` | `MaCategorieDetailView` | `IsAuthenticated`, propre partenaire requis | PATCH : champs acceptés par `MaCategorieSerializer`, notamment image de couverture | `MaCategorieSerializer` |
| GET | `/api/v1/auth/appareils/` | `MesAppareilsView` | `IsAuthenticated` | aucun | liste `SessionAppareilSerializer` : `id`, `appareil_nom`, `appareil_id`, `plateforme`, `adresse_ip`, `derniere_activite_le`, `est_active`, `cree_le` ; tous RO |
| POST | `/api/v1/auth/appareils/<uuid:pk>/revoquer/` | `RevoquerAppareilView` | `IsAuthenticated` | aucun | `message` |
| GET | `/api/v1/auth/partenaires/<int:pk>/` | `VitrinePartenaireView` | `AllowAny` | aucun | `VitrinePartenaireSerializer`, tous RO : `id`, `nom_commerce`, `type_partenaire`, `type_partenaire_libelle`, `description`, `logo`, `photo_couverture`, `adresse`, `quartier`, `secteur`, `ville`, `departement`, `region`, `description_acces`, `telephone_pro`, `whatsapp`, `email_pro`, `nombre_likes`, `nb_vues`, `est_like_par_moi`, `est_favori_par_moi` |

# Catalogue

## `/api/v1/catalogue/`

### Routes explicites

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET | `/api/v1/catalogue/recherche/` | `RechercheUnifieeView` | public (`AllowAny`/permission déclarée dans la vue) | query params de recherche, notamment texte et filtres | réponse de recherche unifiée construite par la vue : articles/partenaires selon la recherche |
| GET | `/api/v1/catalogue/carte/partenaires/` | `CartePartenairesView` | public | query `categorie?`, localité/portée selon la vue | liste manuelle des partenaires visibles avec coordonnées et informations de carte |
| GET | `/api/v1/catalogue/partenaire/<int:partenaire_id>/videos/` | `VideosPartenaireView` | public | aucun | liste `ArticleVideoSerializer` : `id` RO, `article`, `article_nom` RO, `article_slug` RO, `video`, `titre`, `miniature`, `ordre`, `est_active` |
| GET | `/api/v1/catalogue/partenaire/stats-vues/` | `StatsVuesPartenaireView` | authentifié, partenaire requis | query params éventuels de période | statistiques de vues du partenaire, sortie manuelle |
| GET | `/api/v1/catalogue/categories/<slug:slug>/partenaires/` | `PartenairesParCategorieView` | public | aucun | liste manuelle des partenaires actifs de la catégorie |
| POST | `/api/v1/catalogue/articles/<slug:slug>/vue/` | `EnregistrerVueView` | public | `source?`, `duree_secondes?` | `message` |
| GET, PUT, PATCH | `/api/v1/catalogue/articles/<slug:slug>/logement/` | `LogementView` | GET public ; écriture `EstPartenaireProprietaireOuLectureSeule` | PUT/PATCH : `nb_chambres`, `nb_sdb`, `surface_m2`, `meuble`, `duree_min_jours`, `caution`, `equipements`; `article` RO | `LogementSerializer` : `id`, `article` RO, `nb_chambres`, `nb_sdb`, `surface_m2`, `meuble`, `duree_min_jours`, `caution`, `equipements` |
| GET, PUT, PATCH | `/api/v1/catalogue/articles/<slug:slug>/vehicule/` | `VehiculeView` | GET public ; écriture `EstPartenaireProprietaireOuLectureSeule` | PUT/PATCH : `marque`, `modele`, `annee`, `kilometrage`, `carburant`, `boite_vitesse`, `places`, `mode`; `article` RO | `VehiculeSerializer` : `id`, `article` RO, `marque`, `modele`, `annee`, `kilometrage`, `carburant`, `boite_vitesse`, `places`, `mode` |

### Viewsets générés par `DefaultRouter`

Les viewsets sont exposés avec les routes standard DRF listées ci-dessous. `CategorieViewSet` est en lecture seule ; les autres utilisent `EstPartenaireProprietaireOuLectureSeule` : lecture publique, écriture réservée au partenaire propriétaire.

| Ressource | Routes | Méthodes | Serializer de sortie / entrée |
|---|---|---|---|
| catégories | `/api/v1/catalogue/categories/`, `/api/v1/catalogue/categories/<slug:slug>/` | GET liste ; GET détail | `CategorieSerializer` : `id`, `nom`, `slug`, `description`, `icone`, `image_couverture`, `parent`, `mode_transaction`, `types_articles`, `affiche_catalogue`, `module_flutter`, `ordre`, `est_active`, `nb_partenaires`, `enfants`, `types_partenaire` ; lecture seule par nature du viewset |
| articles | `/api/v1/catalogue/articles/`, `/api/v1/catalogue/articles/<slug:slug>/` | GET liste/détail, POST, PUT, PATCH, DELETE | liste : `ArticleListeSerializer`; détail/écriture : `ArticleDetailSerializer`. Entrée article : `nom`, `description`, `type`, `prix`, `prix_promotion`, `unite`, `details`, `est_actif`, `est_disponible`, `est_en_promotion`, `temps_preparation_min`, `categorie`, `section_menu` ; `slug`, compteurs (`nb_vues`, `nb_likes`, `nb_commentaires`, `nb_favoris`) et `partenaire` RO. Sortie détail : champs précédents + `pourcentage_reduction` RO, `prix_effectif` RO, `promotion_valide` RO, `partenaire_nom` RO, `images`, `videos`, `variantes`, `supplements`, `panoramas`, `logement`, `vehicule`, `est_like_par_moi`, `est_favori_par_moi`, `created_at`, `updated_at` |
| images | `/api/v1/catalogue/images/`, `/api/v1/catalogue/images/<int:pk>/` | GET liste/détail, POST, PUT, PATCH, DELETE | `ArticleImageSerializer` : entrée `article`, `image`, `legende`, `ordre`, `est_principale`; sortie + `id`; `est_active` RO |
| vidéos | `/api/v1/catalogue/videos/`, `/api/v1/catalogue/videos/<int:pk>/` | GET liste/détail, POST, PUT, PATCH, DELETE | `ArticleVideoSerializer` : entrée `article`, `video`, `titre`, `miniature`, `ordre`, `est_active`; sortie `id` RO, `article_nom` RO, `article_slug` RO |
| variantes | `/api/v1/catalogue/variantes/`, `/api/v1/catalogue/variantes/<int:pk>/` | GET liste/détail, POST, PUT, PATCH, DELETE | `VarianteSerializer` : `id`, `article`, `nom`, `prix_supplement`, `est_par_defaut`, `ordre`, `est_active` |
| suppléments | `/api/v1/catalogue/supplements/`, `/api/v1/catalogue/supplements/<int:pk>/` | GET liste/détail, POST, PUT, PATCH, DELETE | `SupplementSerializer` : `id`, `article`, `nom`, `prix`, `est_optionnel`, `ordre`, `est_actif` |
| panoramas | `/api/v1/catalogue/panoramas/`, `/api/v1/catalogue/panoramas/<int:pk>/` | GET liste/détail, POST, PUT, PATCH, DELETE | `PanoramaSerializer` : `id`, `article`, `image`, `nom_piece`, `ordre`, `est_active` |

Filtres catalogue observés : articles `?categorie=`, `?partenaire=`, `?type=`, `?recherche=`, `?localites=` ; sous-ressources `?article=`.

# Social

## `/api/v1/social/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| POST | `/api/v1/social/articles/<int:pk>/like/` | `ToggleLikeArticle` | `IsAuthenticated` | aucun | `actif`, `total` |
| POST | `/api/v1/social/articles/<int:pk>/favori/` | `ToggleFavoriArticle` | `IsAuthenticated` | aucun | `actif`, `total` |
| POST | `/api/v1/social/partenaires/<int:pk>/like/` | `ToggleLikePartenaire` | `IsAuthenticated` | aucun | `actif`, `total` (total `null` car aucun compteur configuré) |
| POST | `/api/v1/social/partenaires/<int:pk>/favori/` | `ToggleFavoriPartenaire` | `IsAuthenticated` | aucun | `actif`, `total` (`null`) |
| GET | `/api/v1/social/mes-favoris/` | `MesFavorisView` | `IsAuthenticated` | aucun | `articles`: liste `FavoriArticleSerializer` (`id`, `article`, `created_at`) ; `partenaires`: liste `FavoriPartenaireSerializer` (`id`, `partenaire`, `created_at`) |
| GET | `/api/v1/social/mes-likes/` | `MesLikesView` | `IsAuthenticated` | aucun | `articles`: liste d'IDs ; `partenaires`: liste d'IDs |
| GET | `/api/v1/social/commentaires/articles/` | `CommentaireArticleViewSet` | `EstAuteurOuModerateurOuLectureSeule` ; lecture publique | query `?article=<id>` | liste `CommentaireArticleSerializer` : `id`, `user` RO, `user_nom`, `article`, `parent`, `contenu`, `est_visible` RO, `est_modifie` RO, `nb_likes` RO, `est_like_par_moi`, `reponses`, `created_at`, `updated_at` |
| POST | `/api/v1/social/commentaires/articles/` | `CommentaireArticleViewSet` | authentifié via permission custom | `article`, `parent?`, `contenu` ; `user`, `est_visible`, `est_modifie`, `nb_likes` RO | commentaire serializer ci-dessus |
| GET, PUT, PATCH, DELETE | `/api/v1/social/commentaires/articles/<int:pk>/` | `CommentaireArticleDetail` | `EstAuteurOuModerateurOuLectureSeule` | PUT/PATCH : `article`, `parent`, `contenu`; champs RO ci-dessus | `CommentaireArticleSerializer` |
| GET | `/api/v1/social/commentaires/partenaires/` | `CommentairePartenaireViewSet` | `EstAuteurOuModerateurOuLectureSeule` ; lecture publique | query `?partenaire=<id>` | liste `CommentairePartenaireSerializer` : `id`, `user` RO, `user_nom`, `partenaire`, `parent`, `contenu`, `est_visible` RO, `est_modifie` RO, `nb_likes` RO, `est_like_par_moi`, `reponses`, `created_at`, `updated_at` |
| POST | `/api/v1/social/commentaires/partenaires/` | `CommentairePartenaireViewSet` | authentifié via permission custom | `partenaire`, `parent?`, `contenu` | commentaire serializer ci-dessus |
| GET, PUT, PATCH, DELETE | `/api/v1/social/commentaires/partenaires/<int:pk>/` | `CommentairePartenaireDetail` | `EstAuteurOuModerateurOuLectureSeule` | PUT/PATCH : `partenaire`, `parent`, `contenu` | `CommentairePartenaireSerializer` |
| POST | `/api/v1/social/commentaires/<str:type_comm>/<int:pk>/like/` | `ToggleLikeCommentaire` | `IsAuthenticated` | aucun ; `type_comm` vaut `article` ou `partenaire` | `actif`, `total` |

# Orders

## `/api/v1/orders/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET | `/api/v1/orders/paniers/` | `MesPaniersView` | `IsAuthenticated` | aucun | liste `PanierSerializer` : `id`, `partenaire`, `partenaire_nom` RO, `categorie`, `categorie_nom` RO, `lignes` RO (`id`, `article`, `article_nom` RO, `variante_id`, `supplements`, `quantite`, `prix_unitaire` RO, `prix_ligne`, `note_speciale`, `created_at`), `total`, `created_at`, `updated_at` |
| POST | `/api/v1/orders/paniers/ajouter/` | `AjouterLigneView` | `IsAuthenticated` | `article`, `quantite?`, `variante_id?`, `supplement_ids?[]`, `note_speciale?` | panier `PanierSerializer` |
| POST | `/api/v1/orders/paniers/<int:pk>/valider/` | `ValiderPanierView` | `IsAuthenticated` | `mode_livraison?`, `adresse?`, `heure_souhaitee?`, `mode_paiement?`, `notes_client?`, `frais_livraison?`, `latitude?`, `longitude?` ; GPS obligatoire si `mode_livraison=livraison` | `CommandeSerializer` : `id`, `numero` RO, `user` RO, `client_nom`, `client_telephone` RO, `partenaire` RO, `partenaire_nom` RO, `mode_livraison`, `adresse`, `adresse_snapshot`, `heure_souhaitee`, `statut` RO, `raison_refus`, `sous_total` RO, `frais_livraison`, `total` RO, `mode_paiement`, `notes_client`, `notes_partenaire`, `lignes` RO, `created_at`, `acceptee_le`, `prete_le`, `livree_le` |
| DELETE | `/api/v1/orders/paniers/<int:pk>/` | `ViderPanierView` | `IsAuthenticated` | aucun | `message` |
| PATCH, DELETE | `/api/v1/orders/lignes/<int:pk>/` | `LigneDetailView` | `IsAuthenticated` | PATCH : `quantite?`, `note_speciale?` | PATCH : panier `PanierSerializer`; DELETE : panier mis à jour ou `message` |
| GET | `/api/v1/orders/commandes/` | `MesCommandesClientView` | `IsAuthenticated` | query `?statut=` | liste `CommandeSerializer` |
| GET | `/api/v1/orders/commandes/partenaire/` | `CommandesPartenaireView` | `IsAuthenticated`, partenaire requis | query `?statut=` | liste `CommandeSerializer` |
| GET | `/api/v1/orders/commandes/<int:pk>/` | `CommandeDetailView` | `IsAuthenticated`, client propriétaire ou partenaire concerné | aucun | `CommandeSerializer` |
| POST | `/api/v1/orders/commandes/<int:pk>/transition/` | `TransitionCommandeView` | `IsAuthenticated`, acteur autorisé selon commande | `statut`, `raison_refus?` | `CommandeSerializer` |
| POST | `/api/v1/orders/commandes/<int:pk>/livreur/` | `CommanderLivreurView` | `IsAuthenticated`, client/partenaire autorisé | champs de demande de livreur lus par la vue | commande/course selon la vue |

# Messaging

## `/api/v1/messaging/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET, POST | `/api/v1/messaging/interventions/` | `DemandesView` | `IsAuthenticated` | POST : `artisan`, `type_intervention?`, `type_libre?`, `description?`, `urgence?`, `adresse?`, `description_acces?`, `disponibilite_preferee?`, `latitude?`, `longitude?` | liste/création `DemandeInterventionSerializer` : `id`, `numero` RO, `user` RO, `client_nom`, `artisan`, `artisan_nom` RO, `client_telephone` RO, `artisan_telephone`, `type_intervention`, `type_libre`, `description`, `urgence`, `latitude`, `longitude`, `adresse`, `adresse_snapshot`, `description_acces`, `disponibilite_preferee`, `statut` RO, `date_proposee` RO, `prix_propose` RO, `raison_refus` RO, `conversation` RO, `photos`, `created_at` |
| GET | `/api/v1/messaging/interventions/artisan/` | `DemandesArtisanView` | `IsAuthenticated`, artisan requis | query `?statut=` | liste `DemandeInterventionSerializer` |
| GET | `/api/v1/messaging/interventions/<int:pk>/` | `DemandeDetailView` | `IsAuthenticated`, client ou artisan concerné | aucun | `DemandeInterventionSerializer` |
| POST | `/api/v1/messaging/interventions/<int:pk>/transition/` | `TransitionDemandeView` | `IsAuthenticated`, client ou artisan concerné | `statut`, `date_proposee?`, `prix_propose?`, `raison_refus?` | `DemandeInterventionSerializer` |
| POST | `/api/v1/messaging/interventions/<int:pk>/photos/` | `AjouterPhotoView` | `IsAuthenticated`, client propriétaire | `image`, `legende?`, `ordre?` ; `demande` est ajouté par la vue | `DemandeInterventionPhotoSerializer` : `id`, `demande`, `image`, `legende`, `ordre`, `created_at` RO |
| GET, POST | `/api/v1/messaging/conversations/` | `ConversationsView` | `IsAuthenticated` | POST : `partenaire`, `article?` | GET liste `ConversationSerializer` : `id`, `client` RO, `client_nom`, `partenaire`, `partenaire_nom` RO, `article`, `client_telephone` RO, `partenaire_telephone`, `derniere_activite`, `est_archivee`, `dernier_message`, `created_at`; POST ajoute `nouvelle` |
| GET | `/api/v1/messaging/conversations/<int:pk>/messages/` | `MessagesView` | `IsAuthenticated`, participant uniquement | aucun | liste `MessageSerializer` : `id`, `conversation`, `expediteur` RO, `expediteur_nom`, `type`, `contenu`, `media_url`, `statut` RO, `created_at` |
| POST | `/api/v1/messaging/contacter/` | `ContacterView` | `IsAuthenticated` | `article` ou `partenaire` (un des deux requis) | `ConversationSerializer` + `nouvelle` |

# Livreurs

## `/api/v1/livreurs/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| POST | `/api/v1/livreurs/position/` | `MaPositionView` | `IsAuthenticated`, profil livreur requis | `latitude`, `longitude` | `message` |
| POST | `/api/v1/livreurs/position-transpondeur/` | `PositionTranspondeurView` | `AllowAny` ; identification par `transpondeur_id` | `transpondeur_id`, `latitude`, `longitude` | `message` |
| POST | `/api/v1/livreurs/statut/` | `MonStatutView` | `IsAuthenticated`, profil livreur requis | `statut` : `en_ligne` ou `hors_ligne` | `message` |
| GET | `/api/v1/livreurs/proches/` | `LivreursProchesView` | `IsAuthenticated` | query `?lat=`, `?lng=` optionnels | liste manuelle : `id`, `nom`, `type_vehicule`, `latitude`, `longitude`, `position_maj_le` |

# Livraison

## `/api/v1/livraison/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET | `/api/v1/livraison/tarif/` | `TarifView` | `AllowAny` | aucun | `prix_course` |
| GET | `/api/v1/livraison/icones-motard/` | `IconesMotardView` | `AllowAny` | aucun | `standard`, `terminee` (URLs absolues ou `null`) |
| GET | `/api/v1/livraison/courses/` | `MesCoursesView` | `IsAuthenticated` | query `?statut=` | liste manuelle `_course_dict` : `id`, `numero`, `statut`, `ville`, `description_colis`, `prix`, `point_a`, `point_b`, `livreur`, `livreur_position`, `position_b_deposee`, `cree_le` |
| POST | `/api/v1/livraison/courses/creer/` | `CreerCourseView` | `IsAuthenticated` | requis : `ville`, `a_quartier`, `a_nom_contact`, `a_telephone_contact`, `b_quartier`, `b_nom_contact`, `b_telephone_contact`; optionnels : `a_latitude`, `a_longitude`, `b_latitude`, `b_longitude`, `description_colis`, `prix` | `course` avec `_course_dict` + `assigne`, `message?` |
| GET | `/api/v1/livraison/courses/recues/` | `CoursesRecuesView` | `IsAuthenticated` | query `?statut=` | liste `_course_dict` |
| GET | `/api/v1/livraison/courses/<uuid:pk>/` | `CourseDetailView` | `IsAuthenticated`, demandeur, livreur assigné ou destinataire | aucun | `_course_dict` + `je_suis_livreur`, `je_suis_destinataire` |
| POST | `/api/v1/livraison/courses/<uuid:pk>/position-contact/` | `PositionContactView` | `IsAuthenticated`, destinataire de la course | `latitude`, `longitude` | `_course_dict` |
| POST | `/api/v1/livraison/courses/<uuid:pk>/transition/` | `TransitionCourseView` | `IsAuthenticated`, demandeur ou livreur assigné selon transition | `statut`, `raison_refus?` | `_course_dict` |

# Payments

## `/api/v1/payments/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET, POST | `/api/v1/payments/paiements/` | `PaiementsView` | `IsAuthenticated`; flag `paiement_actif` requis, sinon 503 | POST : `partenaire`, `type_objet`, `objet_id`, `montant`, `mode`, `reference_externe?`, `note?`; `user`, `statut` RO | liste ou objet `PaiementSerializer` : `id`, `user` RO, `partenaire`, `type_objet`, `objet_id`, `montant`, `mode`, `statut` RO, `reference_externe`, `note`, `valide_par` RO, `valide_le` RO, `cree_le`, `modifie_le` |
| POST | `/api/v1/payments/paiements/<uuid:pk>/valider/` | `ValiderPaiementView` | `IsAuthenticated` + admin/staff ; flag requis | `statut` : confirmé/rejeté/remboursé, `note?` | `PaiementSerializer` |

# Notifications

## `/api/v1/notifications/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| POST | `/api/v1/notifications/token/` | `EnregistrerTokenFCMView` | `IsAuthenticated` | `token_fcm` | `message` |
| DELETE | `/api/v1/notifications/token/` | `EnregistrerTokenFCMView` | `IsAuthenticated` | aucun | `message` |

Aucun `serializers.py` n'existe dans cette app ; les réponses et validations sont manuelles.

# Analytics

## `/api/v1/analytics/`

Toutes les vues analytics utilisant le flag `analytics_actif` renvoient HTTP 403 si le flag est désactivé.

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| POST | `/api/v1/analytics/session/demarrer/` | `DemarrerSessionView` | `IsAuthenticated` + flag | `source?` (`mobile` par défaut, `web` accepté) | `session_id` |
| POST | `/api/v1/analytics/session/ping/` | `PingSessionView` | `IsAuthenticated` + flag | `session_id` | `duree_secondes`, `minute_session` |
| POST | `/api/v1/analytics/categorie/visite/` | `VisiteCategorieView` | `IsAuthenticated` + flag | `categorie` (slug) ou `categorie_id` | `message` |
| POST | `/api/v1/analytics/vitrine/vue/` | `VueVitrineView` | `AllowAny` + flag | `partenaire`, `source?`, `avec_catalogue?` | `message` |
| POST | `/api/v1/analytics/livraison/vue/` | `VueServiceLivraisonView` | `AllowAny` + flag | `source?` | `message` |
| GET | `/api/v1/analytics/livraison/client/<int:user_id>/` | `LivraisonStatsClientView` | `IsAuthenticated`, staff requis | aucun | `nb_consultations`, `nb_utilisations_demandeur`, `nb_utilisations_destinataire` |
| GET | `/api/v1/analytics/livraison/partenaire/<int:partenaire_id>/` | `LivraisonStatsPartenaireView` | `IsAuthenticated`, staff requis | aucun | `nb_livreurs_commandes` |
| GET | `/api/v1/analytics/livraison/tableau-de-bord/` | `LivraisonTableauDeBordView` | `IsAuthenticated`, staff requis | query `?debut=YYYY-MM-DD`, `?fin=YYYY-MM-DD` | `genere_le`, `periode`, `taux_conversion`, `ca_total`, `ca_par_periode`, `repartition_demandeurs`, `top_villes`, `top_quartiers_depart`, `top_categories_partenaire` |
| GET | `/api/v1/analytics/livraison/tableau-de-bord/export/` | `LivraisonTableauDeBordExportView` | `IsAuthenticated`, staff requis | query `?debut=`, `?fin=` | CSV `section;cle;valeur` |
| POST | `/api/v1/analytics/intervention/ouverture/` | `OuvertureDemandeInterventionView` | `IsAuthenticated` + flag | aucun | `message` |
| GET | `/api/v1/analytics/admin/engagement/` | `EngagementAdminView` | `IsAuthenticated`, staff requis | aucun | `nb_profils`, `nb_clients_actifs`, `profils[]` avec `utilisateur_id`, `telephone`, `username`, compteurs mensuels, `derniere_activite`, `est_client_actif`, `categories_consultees` |
| GET | `/api/v1/analytics/admin/stats-connexion/` | `StatsConnexionAdminView` | `IsAuthenticated`, staff requis | aucun | tableau de bord : `genere_le`, `en_ligne`, `comptes`, `connexions_distinctes`, `ouvertures` |
| GET | `/api/v1/analytics/admin/stats-connexion/export/` | `StatsConnexionExportView` | `IsAuthenticated`, staff requis | query `?jours=N` | CSV détaillé des sessions : `id`, `utilisateur`, `role`, `source`, `debut`, `dernier_ping`, `duree_secondes`, `active` |

# Publicités

## `/api/v1/publicites/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET | `/api/v1/publicites/formules/` | `FormulesView` | `IsAuthenticated` | aucun | liste `FormulePubliciteSerializer` : `id`, `nom`, `prix`, `priorite`, `duree_jours`, `passages_par_jour`, `duree_affichage_secondes`, `quota_partenaires`, `acces_heures_affluence`, `types_affichage`, `nb_images_max`, `video_autorisee`, `duree_video_max_secondes`, `cible_pourcentage_actifs` |
| GET | `/api/v1/publicites/` | `PagePublicitesView` | `AllowAny` | aucun | `{publicites: [...]}` avec `PubliciteListSerializer` : `id`, `titre`, `image_couverture`, `partenaire_id` RO, `duree_affichage_secondes` RO, `priorite` RO |
| GET | `/api/v1/publicites/carrousel/` | `CarrouselView` | `AllowAny` | aucun | `{publicites: [...]}` avec `PubliciteListSerializer` |
| GET | `/api/v1/publicites/interstitiel/` | `InterstitielView` | `IsAuthenticated` | query `?minute_session=N` | `{publicite: ...}` avec `PubliciteDetailSerializer`, ou `null` |
| GET | `/api/v1/publicites/bandeau-bas/` | `BandeauBasView` | `AllowAny` | aucun | `{publicite: ...}` avec `PubliciteListSerializer`, ou `null` |
| GET | `/api/v1/publicites/<uuid:pk>/` | `PubliciteDetailView` | `AllowAny` | aucun | `PubliciteDetailSerializer` : `id`, `titre`, `description`, `image_couverture`, `video`, `images` (`id`, `image`, `ordre`), `partenaire_id` RO, `nom_partenaire` RO, `portee`, `portee_effective` RO |
| POST | `/api/v1/publicites/<uuid:pk>/impression/` | `EnregistrerImpressionView` | `AllowAny` | `cliquee?`, `type_affichage?`, `session_id?`, `minute_session?` | `message` |
| GET, POST | `/api/v1/publicites/mes-publicites/` | `MesPublicitesView` | `IsAuthenticated`, partenaire requis pour POST | POST : `formule`, `titre`, `description`, `image_couverture`, `video`, `portee`; `statut` RO | liste/création `PubliciteCreationSerializer` : `id`, `formule`, `titre`, `description`, `image_couverture`, `video`, `portee`, `statut` RO |
| POST | `/api/v1/publicites/<uuid:pk>/transition/<str:action>/` | `TransitionPubliciteView` | `IsAuthenticated`; partenaire pour soumettre, admin pour actions admin | aucun body requis par la vue | `statut`, `message` |
| GET | `/api/v1/publicites/mes-stats/` | `StatsPartenaireView` | `IsAuthenticated`, partenaire requis | aucun | `{publicites: [...]}` : stats détaillées ou `stats_disponibles: false`, avec `id`, `titre`, `formule`, `statut`, compteurs et dates selon visibilité |
| GET | `/api/v1/publicites/admin/stats/` | `StatsAdminView` | `IsAuthenticated`, staff requis | aucun | `totaux` (`nb_publicites`, `nb_actives`, `total_impressions`, `total_personnes_touchees`, `total_clics`) + `publicites[]` détaillées |
| GET | `/api/v1/publicites/admin/export/` | `ExportCSVView` | `IsAuthenticated`, staff requis | query `?type=publicites|impressions|profils|sessions` | CSV selon le type demandé |

# Géographie

## `/api/v1/geo/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET | `/api/v1/geo/departements/` | `DepartementsView` | `AllowAny` | aucun | liste `DepartementSerializer` : `id`, `nom`, `region` RO, `district` RO |
| GET | `/api/v1/geo/quartiers/` | `QuartiersView` | `AllowAny` | query `?departement=<id>` optionnel | liste `QuartierSerializer` : `id`, `nom` |

# Version

## `/api/v1/version/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET | `/api/v1/version/verifier/` | `VerifierVersionView` | `AllowAny` | query `?version=X.Y.Z`, `?plateforme=android|ios` | `statut`, `obligatoire`, `lien_store`, `message`, `version_min_obligatoire`, `version_conseillee` |

# Administration

## `/api/v1/administration/`

| Méthode | Chemin | Vue | Permission | Entrée | Sortie |
|---|---|---|---|---|---|
| GET | `/api/v1/administration/dashboard/` | `DashboardG5View` | `IsAuthenticated` + `ADroitDe('voir_stats')` | aucun | stats de connexion + `appareils` + `comptes_par_statut` |
| GET | `/api/v1/administration/appareils/export/` | `AppareilsExportView` | `IsAuthenticated` + `ADroitDe('exporter_csv')` | query `?actives=0` pour inclure les inactifs | CSV appareils |
| POST | `/api/v1/administration/moderation/` | `ModerationView` | `IsAuthenticated` + `EstSuperAdmin` | `cible_id`, `action` (`suspendre`, `reactiver`, `bannir`, `supprimer_soft`, `supprimer_hard`, `restaurer`), `motif?` | `detail`, `action` |
| GET | `/api/v1/administration/moderation/journal/` | `JournalModerationView` | `IsAuthenticated` + `ADroitDe('lire_journal')` | aucun | `total`, `entrees[]` : `date`, `action`, `action_libelle`, `acteur`, `cible`, `cible_role`, `motif` |
| GET | `/api/v1/administration/moderation/journal/export/` | `JournalExportView` | `IsAuthenticated` + `ADroitDe('lire_journal', 'exporter_csv')` | aucun | CSV du journal |
| GET | `/api/v1/administration/partenaires/` | `IndicateursPartenairesView` | `IsAuthenticated` + `ADroitDe('voir_indicateurs')` | aucun | tableau de bord indicateurs partenaires, sortie manuelle |
| GET | `/api/v1/administration/partenaires/export/` | `PartenairesExportView` | `IsAuthenticated` + `ADroitDe('exporter_csv')` | aucun | CSV partenaires |
| POST, DELETE | `/api/v1/administration/partenaires/<int:pk>/faveur/` | `FaveurView` | `IsAuthenticated` + `ADroitDe('accorder_faveur')` | POST : `plan_code`, `motif?`; DELETE : `motif?` | profil `MonProfilPartenaireSerializer` |
| POST, DELETE | `/api/v1/administration/publicites/<uuid:pk>/faveur/` | `FaveurPubliciteView` | `IsAuthenticated` + `ADroitDe('offrir_campagne')` | `motif?` | `id`, `titre`, `statut`, `est_faveur`, `debut_diffusion`, `fin_diffusion`, `faveur_motif` |
| GET, POST | `/api/v1/administration/demandes-partenariat/` | `DemandesPartenariatView` | `IsAuthenticated` + `ADroitDe('valider_devenir_partenaire')` | POST : `partenaire_id`, `decision` (`accepter` ou `rejeter`), `motif?` | GET : `total`, `demandes[]` avec `id`, `nom_commerce`, `telephone`, `nom_complet`, `departement`, `type_partenaire`, `cree_le`; POST : résultat de décision |

# Routes hors `/api/v1/`

Elles ne font pas partie de l'API REST demandée, mais sont présentes dans le routage racine : `/admin/` (Django admin), `/admin/tableau-de-bord/` (tableau de bord HTML), et les fichiers médias en mode `DEBUG`.
