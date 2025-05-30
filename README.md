💻🚌 Affichage Bus
Prototype Bêta d’un écran interactif temps réel pour JUNIA Ingénieurs

Affichage Bus est une application embarquée développée en Python / Pygame pour afficher, en un seul coup d’œil dans le hall de JUNIA, les informations suivantes :
- 🌤️ Météo locale (rafraîchie chaque minute via l’API Open-Meteo)  
- 🚌 Horaires en temps réel des bus Ilévia  
- 🚲 Disponibilité V’LILLE (station la plus proche)

Le tout tourne sur un Raspberry Pi 4 connecté à un écran PC (HDMI)

📦 Caractéristiques

- Interface full-screen responsive, conçue pour la lisibilité à distance  
- Animations légères (nuages en mouvement, icônes animées)  
- Système de cache local (fichier JSON ou Redis) pour limiter les appels API  
- Architecture non bloquante : threads / asyncio pour séparer rafraîchissement des données et rendu graphique  
- Extensible : ajout aisé de nouveaux flux (RSS, actualités campus, événements…)  

🚀 Installation

1. Cloner le dépôt sur ton PC/Raspberry

2. Installer les dépendances

Sur Windows ou Raspberry Pi OS : 
- pip install pygame
- pip install requests

Si tu utilises un Raspberry Pi, il peut être nécessaire d’installer les dépendances système pour Pygame :
- sudo apt update
- sudo apt install python3-pygame python3-pip

3. Préparer les icônes : 
crée un dossier icons/ à la racine du projet et ajoute les images suivantes :

- sunny.png, cloudy.png, rainy.png, windy.png (icônes météo)
- temp.png, humidity.png (température et humidité)
- vlille.png (logo V'Lille)
- junia.png, ilevia.png (logos partenaires)
- busL5aller.png, busL5retour.png, bus18aller.png, bus18retour.png (icônes bus par ligne et direction)

Astuce : Les noms doivent correspondre exactement à ceux attendus dans le code.

4. Lancer l’application
python affichagebus.py

L’application s’ouvre en plein écran.
Pour quitter, utilise Alt+F4 ou Ctrl+C dans le terminal.


🎨 Personnalisation : 

Pour changer l’arrêt de bus ou la station V’Lille, modifie les variables NOM_STATION et STATION_VLILLE en haut du fichier affichagebus.py.
Les durées d’affichage de chaque page sont dans la liste PAGE_DURATIONS.

🛠️ Dépannage : 

Si tu rencontres une erreur liée à Pygame sur Raspberry Pi, vérifie que tu as bien installé python3-pygame via apt.
Si les données ne s’affichent pas, vérifie ta connexion Internet et l’accessibilité des APIs.

🔗 Licence

Projet open-source sous licence MIT.
