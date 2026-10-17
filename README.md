# Suivi d'entretien de piscines — Flask + PostgreSQL local

Page unique identique à l'application d'origine (onglets Saisie / Historique / Graphiques, recherche en direct, courbes SVG),
avec un JavaScript du même domaine (`static/app.js`, aucun CDN, aucun script inline) qui dialogue avec une API JSON Flask.
Les droits sont vérifiés **côté serveur** à chaque appel (le JS ne fait que masquer les boutons).
La base PostgreSQL est sur la même machine, accessible uniquement via socket Unix (pas de port ouvert).

## Rôles
- **admin** (vous) : (API en écriture : `POST /api/pools/<id>/checks`, `PUT|DELETE /api/checks/<id>`) crée piscines et clients, saisit/modifie/supprime les contrôles, associe les clients aux piscines.
- **client** : lecture seule (historique, graphiques, export CSV) des piscines qui lui sont associées. Toute autre piscine renvoie 404.

## Installation (Ubuntu 24.04 sur EC2)
```bash
sudo apt install -y python3-venv postgresql nginx certbot python3-certbot-nginx
sudo useradd --system --home /opt/piscine --shell /usr/sbin/nologin piscine
sudo mkdir -p /opt/piscine && sudo cp -r . /opt/piscine && sudo chown -R piscine:piscine /opt/piscine
cd /opt/piscine && sudo -u piscine python3 -m venv venv && sudo -u piscine venv/bin/pip install -r requirements.txt

# Base : rôle = utilisateur système => authentification "peer", aucun mot de passe de base à gérer
sudo -u postgres createuser piscine
sudo -u postgres createdb -O piscine piscine

sudo cp deploy/piscine.env.example /etc/piscine.env   # puis éditer SECRET_KEY
sudo chown root:piscine /etc/piscine.env && sudo chmod 640 /etc/piscine.env

# Schéma + premier administrateur
sudo -u piscine env $(grep -v '^#' /etc/piscine.env | xargs) venv/bin/flask --app app init-db
sudo -u piscine env $(grep -v '^#' /etc/piscine.env | xargs) venv/bin/flask --app app create-admin vous@exemple.ch --name "Olivier"

sudo cp deploy/piscine.service /etc/systemd/system/ && sudo systemctl enable --now piscine
sudo cp deploy/nginx-piscine.conf /etc/nginx/sites-available/piscine
sudo ln -s /etc/nginx/sites-available/piscine /etc/nginx/sites-enabled/ && sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d piscine.example.com            # HTTPS obligatoire (cookie de session "Secure")
```
Security group EC2 : ouvrir 80/443 (et 22 restreint à votre IP). **Ne pas** ouvrir 5432.

## Sauvegardes
`pg_dump piscine | gzip > /var/backups/piscine-$(date +%F).sql.gz` en cron quotidien, puis copie hors de l'instance (S3, par ex.).

## Migration depuis l'ancienne version
Les données de l'ancienne app sont en localStorage / Supabase (export JSON ou CSV disponible dans l'ancienne page) ; un import est facile à ajouter si besoin.
