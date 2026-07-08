# Veille logement CROUS — Lyon

Détecte l'apparition de nouvelles annonces sur la recherche CROUS Lyon
(bounds fixés dans `scraper.py`) et envoie un email par annonce nouvelle.

## Mise en place

1. Créer un dépôt GitHub, y pousser ce dossier.
2. Repository → Settings → Secrets and variables → Actions → New repository secret :
   - `EMAIL_ADDRESS` : adresse d'envoi (ex. Gmail).
   - `EMAIL_PASSWORD` : mot de passe d'application (pas le mot de passe principal — à générer dans les paramètres de sécurité Google si compte Gmail).
   - `RECIPIENT_EMAIL` : adresse de réception (peut être identique à `EMAIL_ADDRESS`).
3. Onglet **Actions** → activer les workflows si demandé.

## Premier test (avant d'activer la planification)

Lancer manuellement via Actions → *Veille logement CROUS Lyon* → *Run workflow*,
plutôt que d'attendre le cron. Vérifier ensuite le fichier
`debug_last_page.html` committé dans le dépôt : il contient le HTML brut
réellement reçu par le script.

Point d'incertitude technique : la page cible est une application
cliente (SPA). `scraper.py` tente d'abord d'extraire un état JSON
injecté côté serveur (motif Nuxt/Next), et retombe sur un parsing HTML
générique si ce motif est absent. Sans accès direct au DOM rendu au
moment de la rédaction (page indisponible : message "Vous êtes trop
nombreux"), les deux chemins d'extraction sont écrits de façon
best-effort. Si `seen_listings.json` reste vide ou incohérent après un
premier passage, `debug_last_page.html` permet d'ajuster
`_search_listings_in_json` (clés réelles des objets annonces) ou
`extract_via_html_cards` (sélecteurs CSS réels) dans `scraper.py`.

## Fonctionnement

- Cron toutes les 20 minutes (`*/20 * * * *`), ajustable dans
  `.github/workflows/monitor.yml`. Le message de sur-fréquentation
  rencontré sur le site suggère une charge déjà importante côté
  serveur — un intervalle plus large (30–60 min) limite le risque de
  blocage par un éventuel anti-bot.
- Premier passage : initialise `seen_listings.json`, aucun email
  envoyé (évite une alerte massive sur l'ensemble des annonces déjà en
  ligne).
- Passages suivants : email envoyé uniquement pour les identifiants
  d'annonces absents de l'état précédent.
