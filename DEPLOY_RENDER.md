# Déployer sur Render, puis connecter un GPT privé

Les fichiers sont préparés pour un déploiement depuis GitHub. La branche de
préparation est `codex/odoo-readonly-connector`. Aucun service
Render n'a été créé et aucune connexion à Odoo n'est encore validée.
Le fichier `render.yaml` propose le plan **Starter, payant**, pour éviter la
mise en veille d'un service gratuit. Vérifier le tarif dans Render avant de
valider la création ; ne pas considérer un service gratuit en veille comme un
hébergement disponible en permanence.

## 1. Placer le code sur GitHub

Ouvrir `jonathanbouhy-hub/API-Odoo` sur GitHub et sélectionner la branche
`codex/odoo-readonly-connector` si elle est disponible : aucune archive n'est
nécessaire dans ce cas. Pour un transfert manuel uniquement, si le dépôt est encore vide,
utiliser le lien **uploading an existing file** ; sinon **Add file → Upload files**.
Si vous utilisez l'archive préparée, l'extraire d'abord puis déposer son contenu,
pas le ZIP lui-même. Garder les sous-dossiers `odoo_bridge` et `tests`.
`render.yaml`, `requirements.lock` et `odoo_bridge` doivent apparaître à la
racine du dépôt. Ne jamais télécharger `.env`, une clé, ou le dossier `.git`.
Valider le commit sur la branche souhaitée et sélectionner cette même branche dans Render.

## 2. Créer le service

Créer un compte sur Render et connecter uniquement le dépôt GitHub nécessaire.
Choisir **New → Blueprint**, sélectionner `API-Odoo` et la branche
`codex/odoo-readonly-connector` (ou `main` si les fichiers y ont été fusionnés).
Render doit détecter `render.yaml` à la racine. Vérifier le plan, la région
disponible et le prix avant de déployer. Pour des données d'entreprise, choisir
la région d'hébergement et les conditions de traitement appropriées.

Renseigner dans l'interface sécurisée Render les paramètres demandés :

| Variable | Valeur |
| --- | --- |
| `ODOO_URL` | `https://odooo.elneo.com` (prérempli ; confirmer l'orthographe) |
| `ODOO_DB` | `odoo17` (nom communiqué par le propriétaire ; à valider par le test) |
| `ODOO_LOGIN` | Votre identifiant de connexion Odoo, souvent votre adresse e-mail |
| `ODOO_API_KEY` | Votre clé API Odoo ; pas votre mot de passe ChatGPT |
| `CONNECTOR_API_KEY` | Générée aléatoirement par Render ; clé distincte pour le GPT |

Ne partager aucune valeur de clé dans GitHub ou le chat. Le compte Odoo actuel
est autorisé pour cette intégration. Le connecteur n'exécute que des lectures,
mais la clé Odoo conserve les droits du compte lorsqu'elle est utilisée ailleurs.

## 3. Vérifier le déploiement

La commande démarre le serveur sur le port attribué par Render. Render fournit
HTTPS et la gestion du processus. Les journaux d'accès Uvicorn sont désactivés
pour ne pas enregistrer les critères de recherche dans les URL. L'application
ne journalise pas les clés ou les corps JSON-RPC. Si vous ajoutez un proxy,
ne pas y activer de journalisation des en-têtes d'authentification ou des corps.

Attendre que le service soit démarré. Son adresse HTTPS est affichée par Render.
`/health` doit répondre `{"status":"ok"}` : cela vérifie uniquement le serveur.
`/openapi.json` fournit le schéma des cinq opérations GET, avec son adresse
publique renseignée automatiquement via `RENDER_EXTERNAL_URL`.

Ne pas ouvrir les URL de recherche dans le navigateur en y ajoutant une clé.
Le test réel Odoo se fera via le test d'Action authentifié décrit ci-dessous.
Un statut Render « Live » ne valide pas les identifiants Odoo.

## 4. Connecter un GPT personnalisé privé

Sur ChatGPT Web, ouvrir la création d'un GPT, puis **Configurer → Actions**.
Si cette option n'est pas visible sur votre compte, préciser ce que l'interface
affiche avant de poursuivre : ne pas souscrire un autre abonnement à l'aveugle.

Importer depuis `https://ADRESSE-DU-SERVICE/openapi.json` (remplacer l'adresse).
Dans **Authentication**, choisir **API Key**, puis **Bearer**. Copier la valeur
de `CONNECTOR_API_KEY` depuis les paramètres sécurisés Render dans ce champ.
Ne jamais y renseigner `ODOO_API_KEY`. Garder le GPT privé.

Ajouter les instructions du README au GPT. Le schéma doit exposer :
`listBusinessModels`, `getBusinessModelFields`, `searchBusinessRecords`,
`listCustomerInvoices` et `getCustomerInvoice`.

## 5. Tester Odoo avant de considérer la connexion opérationnelle

Dans les tests d'Actions, appeler successivement :

1. `listBusinessModels` : teste l'authentification du connecteur, pas Odoo.
2. `getBusinessModelFields` avec `model=res.partner` : teste l'authentification
   Odoo et les droits de lecture des champs.
3. `searchBusinessRecords` avec `model=res.partner`, `fields=id,name`, `limit=1`.
   Comparer le résultat à un contact connu dans Odoo.
4. Consulter un devis, une commande et une facture connus via `sale.order` et
   `account.move`, en suivant les exemples du README et les champs disponibles.

Un résultat vide n'établit pas que toutes les données sont accessibles.
Une erreur **401** concerne généralement la clé du connecteur ; une **503**, sa
configuration manquante/invalide ; une **502**, la communication Odoo, les
identifiants, le nom de base, le module ou ses droits. Ne pas communiquer de
journaux contenant des secrets ou des données clients pour diagnostiquer.

Seules les conversations avec ce GPT disposent de l'Action. Cette installation
ne connecte pas automatiquement toutes les conversations ChatGPT à Odoo.
