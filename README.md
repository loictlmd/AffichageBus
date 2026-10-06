# AffichageBus V3 🎓

Écran d’informations pour le hall de JUNIA, conçu en Python et Pygame pour tourner en continu sur un Raspberry Pi.

## Ce que montre l’écran

- 🚌 **Bus Ilévia** : prochains départs des lignes L5 et 18 à l’arrêt Solférino, dans les deux directions. Les horaires du flux MEL sont interprétés dans le fuseau de Lille.
- 🌤️ **Météo** : conditions actuelles et prévisions des trois prochains jours à Lille.
- 🚲 **V’Lille** : vélos et places disponibles à la station Palais Rameau.
- 📅 **Vie du campus** : prochains événements, association organisatrice et, si `icons/qrcode.png` est présent, un QR code pour proposer un événement.

Les quatre pages défilent automatiquement toutes les **10 secondes**. La colonne de droite résume la météo et les V’Lille, puis alterne entre le prochain événement et les prochains bus. Les données sont récupérées en arrière-plan ; la dernière réponse reçue reste en mémoire si une API est momentanément inaccessible. Les mentions d’actualisation sont masquées à l’écran.

## Installation sur Windows 🪟

Installer Python 3.9 ou plus récent, puis ouvrir PowerShell dans le dossier du projet :

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe affichagebusV3.py --windowed --size 1280x720
```

Le paquet `tzdata` dans `requirements.txt` fournit le fuseau `Europe/Paris`, nécessaire notamment sous Windows. Pour tester sans connexion aux API, ajouter `--demo` à la dernière commande. Appuyer sur **Échap** pour fermer la fenêtre.

## Installation sur Raspberry Pi 🍓

Depuis le dossier du projet, avec Python 3.9 ou plus récent :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python affichagebusV3.py
```

Le lancement normal ouvre l’affichage en plein écran. Si un service lance déjà l’ancien fichier `affichagebus.py`, modifier sa commande pour pointer vers **`affichagebusV3.py`** : ce dépôt ne contient plus qu’un seul script Python.

## Fichiers et réglages ⚙️

- `affichagebusV3.py` : application et paramètres en haut du fichier (lignes, stations, URL, couleurs, fréquences).
- `requirements.txt` : dépendances Python.
- `icons/` : logo et images utilisés par l’affichage ; garder ce dossier à côté du script. Le QR code `icons/qrcode.png` est facultatif.

Les appels aux API bus, V’Lille et événements sont renouvelés toutes les minutes ; la météo actuelle toutes les cinq minutes ; les prévisions toutes les quinze minutes. Aucun compte ni clé API n’est requis par le code actuel.
