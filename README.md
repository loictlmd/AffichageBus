# Affichage Bus — JUNIA

Écran d’information du hall de JUNIA, développé en Python/Pygame pour fonctionner en continu sur Raspberry Pi.

## Version actuelle : V3

- Quatre pages : événements de l’école, bus Ilévia, météo sur trois jours et disponibilité V’Lille.
- Arrêt **Solférino**, lignes **L5** et **18** ; station V’Lille **Palais Rameau**.
- Bandeau JUNIA violet, logo blanc, date et heure de Paris ; informations essentielles dans la colonne droite.
- Agenda adapté au nombre d’événements ; QR code pour proposer un événement.
- Prochain bus par ligne avec destination et temps d’attente dans le résumé latéral.
- Images météo chargées depuis `icons/` ; pictogrammes de secours si une image manque.
- Appels réseau dans des workers séparés, sessions HTTP réutilisées et caches de rendu bornés.
- Dernières données reçues conservées **en mémoire** pendant une panne ; mentions d’actualisation masquées.
- Pas de barre de progression, d’onglets en bas ni de logo Ilévia en pied de page.
- Conteneurs agrandis et alignés en bas ; contenu conservé depuis le fichier fourni.

## Installation

Python **3.9+**, Pygame **2.x**, `requests` et les données du fuseau `Europe/Paris` sont requis.

```bash
git clone https://github.com/loictlmd/AffichageBus.git
cd AffichageBus
python3 -m pip install -r requirements.txt
```

Sur Raspberry Pi OS, si les dépendances système sont nécessaires :

```bash
sudo apt install python3-pygame python3-requests tzdata
```

Si le démarrage automatique utilise un environnement virtuel, installer les dépendances dans ce même environnement.

## Lancement

La commande historique reste valable :

```bash
python3 affichagebus.py
```

`affichagebus.py` lance la V3, dont le code est dans `affichagebusV3.py`.

Test en fenêtre avec les vraies API :

```bash
python3 affichagebus.py --windowed --size 1280x720
```

Test hors réseau avec données fictives :

```bash
python3 affichagebus.py --demo --windowed --size 1280x720
```

Échap, fermeture de fenêtre, Ctrl+C ou SIGTERM arrêtent l’application.

## Mise à jour du Raspberry Pi

Après arrêt de l’affichage par le mécanisme habituel :

```bash
git pull --ff-only
```

Relancer ensuite avec le mécanisme habituel. Si des modifications locales existent, les conserver avant la mise à jour. Le dépôt ne configure pas lui-même le lancement automatique.

Le dossier `icons/` contient déjà les images météo, les bus et le logo JUNIA. Ajouter le **QR code déjà utilisé sur l’écran** sous `icons/qrcode.png` : ce fichier n’est pas présent dans le dépôt au moment de cette mise à jour. Aucune fausse image QR n’est générée en son absence.

## Configuration

Les réglages sont au début de `affichagebusV3.py` : arrêts, directions, URL des API, couleurs et durées.

| Information | Période de récupération |
|---|---|
| Bus, V’Lille, événements | 60 secondes |
| Météo actuelle | 5 minutes |
| Prévisions | 15 minutes |

Les pages changent toutes les 10 secondes. Le résumé bus/événement alterne toutes les 5 secondes lorsqu’un événement à venir est disponible.

### Horaires Ilévia

Le flux MEL vérifié le 2 octobre 2026 contient des heures locales étiquetées `Z` dans `heure_estimee_depart`. La V3 utilise en priorité le fuseau explicite présent dans `cle_tri`. Le repli propre à ce flux est contrôlé par `MEL_BUS_Z_IS_LOCAL`. Les conversions de l’agenda et de la météo restent indépendantes.

## Pistes envisagées

Extinction nocturne, supervision à distance, annonces prioritaires, interface d’administration et cache persistant : **non implémentés**.

## Licence

Le README historique décrit le projet comme open source sous licence MIT.
