# AffichageBus · JUNIA

Écran d’information du campus : prochains bus de Solférino, météo de Lille,
V’Lille Palais Rameau et événements. Rotation automatique, affichage plein écran
et récupération des données en arrière-plan.

## Installation

Python 3.9 ou plus récent. Depuis le dossier du projet :

```sh
python -m pip install -r requirements.txt
```

La dépendance `tzdata` fournit le fuseau Europe/Paris, notamment sous Windows,
avec gestion automatique des heures d’été et d’hiver.

## Tester sous Windows (PowerShell)

Avec votre environnement `.venv` déjà créé :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe affichagebusV3_1.py --windowed --size 1280x720
```

Ajouter `--demo` pour utiliser des données fictives sans connexion réseau.
Fermer la fenêtre ou appuyer sur Échap pour quitter.

## Raspberry Pi

```sh
python3 affichagebus.py
```

`affichagebus.py` est le lanceur ; `affichagebusV3_1.py` contient l’application.
Les deux noms restent utilisables pour préserver le démarrage automatique existant.
Installer les dépendances dans le même environnement Python que celui du service.

## Fichiers et réglages

- `icons/` contient les images utilisées par l’écran. Conserver ce dossier à côté du script.
- Le QR code est facultatif : placer votre image dans `icons/qrcode.png`.
- Les stations, directions, URL des API et durées sont configurées en haut de `affichagebusV3_1.py`.
- Les images et polices sont mises en cache ; l’écran est redessiné seulement lorsque nécessaire.
- Si un service ne répond plus, ses dernières données restent affichées avec une indication d’indisponibilité ou d’ancienneté.

Le dépôt ne contient pas de tests, de captures d’écran ni de documentation dupliquée.
