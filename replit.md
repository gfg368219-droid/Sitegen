# ProaltsGen

Site web de génération de comptes premium avec authentification Discord OAuth2.

## Stack

- **Backend** : Flask (Python) + psycopg2
- **Bot Discord** : discord.py (asyncpg)
- **Base de données** : PostgreSQL
- **Auth** : Discord OAuth2 (identify, guilds, guilds.join)
- **Déploiement web** : Vercel (app.py)
- **Déploiement bot** : Replit (run.py)

## Lancer (Replit)

```bash
python run.py   # Démarre le bot Discord + le serveur web Flask ensemble
```

## Variables d'environnement requises

| Variable              | Description                                              |
|-----------------------|----------------------------------------------------------|
| `DISCORD_TOKEN`       | Token du bot Discord (déjà configuré)                    |
| `DATABASE_URL`        | URL PostgreSQL                                            |
| `SESSION_SECRET`      | Clé secrète Flask (déjà configuré)                       |
| `DISCORD_CLIENT_ID`   | Client ID OAuth2 de l'application Discord                |
| `DISCORD_CLIENT_SECRET` | Client Secret OAuth2                                  |
| `DISCORD_REDIRECT_URI` | URL de callback OAuth2 (ex: https://monsite.vercel.app/callback) |
| `GUILD_ID`            | ID du serveur Discord pour la vérification des rôles     |

## Rôles Discord

| Rôle    | ID                    | Permissions                                |
|---------|-----------------------|--------------------------------------------|
| Owner   | `1517909085453029487` | Tout l'admin + configurer les cooldowns    |
| Admin   | `1517892778938470531` | Créer/modifier/supprimer services, stock   |

## Pages web

| Route                            | Accès        | Description                     |
|----------------------------------|--------------|---------------------------------|
| `/`                              | Public       | Page d'accueil                  |
| `/login`                         | Public       | Redirection OAuth Discord       |
| `/callback`                      | Public       | Callback OAuth                  |
| `/services`                      | Connecté     | Liste des services              |
| `/services/<id>`                 | Connecté     | Page de génération              |
| `/leaderboard`                   | Public       | Classement des générateurs      |
| `/admin`                         | Admin/Owner  | Panel admin                     |
| `/admin/services/create`         | Admin/Owner  | Créer un service                |
| `/admin/services/<id>/edit`      | Admin/Owner  | Modifier un service             |
| `/admin/services/<id>/delete`    | Admin/Owner  | Supprimer un service            |
| `/admin/services/<id>/stock`     | Admin/Owner  | Ajouter du stock                |
| `/owner`                         | Owner        | Panel owner (cooldowns)         |

## Déploiement Vercel

Le fichier `vercel.json` est déjà configuré. Pour déployer :
1. Connecter le dépôt à Vercel
2. Configurer les variables d'environnement dans le dashboard Vercel
3. `app.py` est le point d'entrée

## Format des fichiers de stock

Un compte par ligne. Deux types supportés :

**email:password** (avec `@`) :
```
user@gmail.com:password123
autre@hotmail.com:pass456
```

**user:password** (sans `@`) :
```
MonPseudo:password123
AutreUtilisateur:pass456
```

Règles : les lignes avec `http/https` sont ignorées. Si `|` est présent, seule la partie avant est prise. Les doublons sont ignorés silencieusement.

## Commandes Discord (inchangées)

| Commande    | Description                     | Rôle requis  |
|-------------|---------------------------------|--------------|
| `/create`   | Créer un service                | Admin/Owner  |
| `/delete`   | Supprimer un service            | Admin/Owner  |
| `/restock`  | Ajouter des comptes (.txt)      | Admin        |
| `/erestock` | Restock sans traitement `\|`    | Admin        |
| `/config`   | Configurer le bot               | Owner        |

## User preferences

- Langue française dans les messages
- Pas d'emojis hardcodés dans le code Python
- Thème sombre violet/bleu (ProaltsGen)
- Architecture : bot Discord séparé du site web, partageant la même DB
