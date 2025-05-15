# AutoCandidature

Un outil automatisé d'envoi d'emails de candidature pour les chercheurs de stage et d'emploi. Le script analyse les sites web des entreprises, génère des lettres de motivation personnalisées via l'API Mistral AI, et envoie des emails professionnels avec CV et lettre de motivation en pièces jointes.

## Workflow complet

Ce projet s'intègre dans un workflow en trois étapes :

```
┌─────────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ google-maps-scraper │ ──> │ improve_csv.py  │ ──> │ sender.py           │
│ (Outil externe)     │     │                 │     │                     │
│                     │     │                 │     │                     │
│ Extraction de       │     │ Nettoyage et    │     │ Génération de       │
│ données Google Maps │     │ validation      │     │ lettres et envoi    │
└─────────────────────┘     └─────────────────┘     └─────────────────────┘
        Étape 1                  Étape 2                  Étape 3
```

1. **Collecte des données** - Utilisation de [google-maps-scraper](https://github.com/gosom/google-maps-scraper) pour extraire des informations d'entreprises depuis Google Maps. Ce scraper génère un fichier CSV brut avec les coordonnées, emails et informations des entreprises.

2. **Nettoyage des données** - Le script `improve_csv.py` transforme et nettoie les données brutes extraites. Il valide les emails, élimine les doublons, et formate les informations dans un CSV prêt à l'emploi.

3. **Envoi automatisé** - Le script `sender.py` prend le CSV nettoyé, génère des lettres de motivation personnalisées avec l'API Mistral, et envoie les candidatures par email avec CV en pièce jointe.

Ce workflow permet d'automatiser entièrement le processus de recherche et de candidature pour un stage ou un emploi.

## Fonctionnalités

- **Scraping intelligent** des sites d'entreprises pour extraire des informations pertinentes
- **Génération de lettres de motivation personnalisées** avec Mistral AI
- **Envoi d'emails professionnels** avec CV et lettre de motivation
- **Suivi des emails** pour éviter les doublons
- **Multithreading** pour accélérer l'envoi des emails
- **Cache de lettres** pour optimiser les requêtes à l'API

## Installation

1. Clonez le dépôt :
```bash
git clone https://github.com/Astray63/autocandidature.git
cd autocandidature
```

2. Installez les dépendances :
```bash
pip install -r requirements.txt
```

3. Configurez vos informations personnelles dans le fichier `.env` (sera créé automatiquement au premier lancement) :
```
# Informations personnelles
NOM_CANDIDAT=Votre Nom
SIGNATURE=

Cordialement,
Votre Nom
Tél: Votre numéro
Email: votre@email.com

# Chemin vers les fichiers
CHEMIN_CV=votre_cv.pdf

# Configuration API
MISTRAL_API_KEY=votre_clé_api_mistral

# Configuration email
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_EXPEDITEUR=votre@email.com
EMAIL_MOT_DE_PASSE=votre_mot_de_passe
EMAIL_DELAY_MIN=5
EMAIL_DELAY_MAX=15
```

> **Important pour les utilisateurs Gmail** : Si vous utilisez Gmail comme serveur SMTP, vous devez créer un "mot de passe d'application" spécifique et ne pas utiliser votre mot de passe Gmail habituel. Google bloque les connexions depuis des applications tierces pour des raisons de sécurité. 
> 
> Pour créer un mot de passe d'application :
> 1. Activez l'authentification à deux facteurs sur votre compte Google
> 2. Rendez-vous sur [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
> 3. Sélectionnez "Autre (nom personnalisé)" dans le menu déroulant
> 4. Entrez un nom (ex: "AutoCandidature")
> 5. Cliquez sur "Générer" et utilisez le mot de passe généré dans votre configuration

## Utilisation

### Étape 1 : Extraction des données avec google-maps-scraper

Commencez par extraire les données d'entreprises depuis Google Maps :

1. Téléchargez le binaire [google-maps-scraper](https://github.com/gosom/google-maps-scraper/releases) correspondant à votre système d'exploitation.

2. Lancez le programme et suivez les instructions de l'interface graphique pour extraire les données d'entreprises qui vous intéressent.

3. Exportez les résultats au format CSV pour passer à l'étape suivante.

### Étape 2 : Nettoyage du fichier CSV

Le fichier obtenu avec google-maps-scraper doit être nettoyé pour récupérer les emails valides :

```bash
python improve_csv.py entreprises_brutes.csv improved_emails.csv
```

Ce script va :
- Extraire et valider les emails
- Nettoyer les URL et les formats incorrects
- Éliminer les doublons
- Formater les données pour l'étape suivante

### Préparation du fichier CSV final

Le fichier CSV nettoyé par `improve_csv.py` contient maintenant les colonnes suivantes :
- `email` : L'adresse email de l'entreprise
- `title` : Le nom de l'entreprise
- `category` : La catégorie/secteur de l'entreprise
- `city` : La ville où est située l'entreprise
- `website` : Le site web de l'entreprise
- Et d'autres informations comme l'adresse complète, le téléphone, etc.

Vous pouvez personnaliser ce fichier si nécessaire avant de passer à l'envoi des emails.

### Étape 3 : Envoi automatisé des candidatures

Une fois votre fichier CSV prêt, lancez l'envoi des candidatures :

```bash
python sender.py improved_emails.csv --sender votre@email.com --password votre_mot_de_passe
```

Options disponibles :
- `--sender`, `-s` : Email de l'expéditeur (peut être défini dans `.env`)
- `--password`, `-p` : Mot de passe de l'email (peut être défini dans `.env`)
- `--cv`, `-c` : Chemin vers votre CV (peut être défini dans `.env`)
- `--dry-run`, `-d` : Mode test (n'envoie pas réellement les emails)
- `--multithreading`, `-m` : Active le multithreading pour un envoi plus rapide
- `--threads`, `-t` : Nombre de threads (défaut: 5)
- `--no-cache`, `-n` : Désactive le cache des lettres de motivation

### Exemple d'utilisation avancée

Pour un envoi rapide avec 10 threads :
```bash
python sender.py entreprises.csv --multithreading --threads 10
```

Pour un test sans envoi réel :
```bash
python sender.py entreprises.csv --dry-run
```

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou à proposer une pull request.

## Licence

Ce projet est sous licence MIT. Voir le fichier LICENSE pour plus de détails.
