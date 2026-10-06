# JUNIA — Affichage du hall V3.1

## Modifications demandées

- Barre de progression et onglets de navigation du bas supprimés.
- Logo JUNIA blanc posé directement sur le bandeau violet, sans cartouche blanc.
- Logo Ilévia retiré du pied de page.
- Horaires bus corrigés avec le décalage explicite présent dans le champ `cle_tri` de l’API.
- Images météo existantes réutilisées en priorité : `sunny.png`, `cloudy.png`, `rainy.png`, `temp.png`, `humidity.png`. Les dessins ne servent plus qu’en cas de fichier manquant ou illisible. `snow.png` et `storm.png` sont acceptés s’ils existent ; sinon les images nuage/pluie prennent le relais.
- Agenda adaptatif : une grande carte pour un événement, deux ou trois cartes sur toute la hauteur, puis une grille pour quatre à six événements. Les groupes suivants restent accessibles au fil du carrousel.
- QR code mieux mis en valeur à côté de l’agenda lorsqu’il y a peu d’événements.
- Bloc bus à droite simplifié : numéro de ligne et heure du prochain départ, tous sens confondus.
- Bloc du prochain événement revu avec calendrier, titre, heure, délai et association.

Les optimisations de la V3 restent en place : réseau dans des workers séparés, cache des images/polices/textes, conservation en mémoire des dernières données reçues et indication discrète si les données sont anciennes. Les mentions « Actualisé à… » ne sont plus affichées.

## Pourquoi les bus avaient deux heures d’avance

La réponse réelle du flux MEL a été vérifiée le 2 octobre 2026 à 11 h 46, puis à 11 h 55, heure de Paris.

Un même passage contenait :

```text
heure_estimee_depart : 2026-10-02T11:47:19Z
cle_tri             : HAUBOURDIN LE PARC/SOLFERINO/2026-10-02T11:47:19.000+02:00
```

Le premier champ étiquette donc « Z » une heure qui correspond ici à l’heure locale. La V3 l’interprétait comme de l’UTC réel, ce qui produisait 13 h 47 à l’écran.

La V3.1 utilise prioritairement la date avec fuseau fournie à la fin de `cle_tri`, puis la convertit en `Europe/Paris`. Si `cle_tri` manque, le repli propre à ce flux traite le `Z` trompeur comme une heure locale. Ce comportement est piloté par `MEL_BUS_Z_IS_LOCAL = True` au début du script. Si la MEL corrige un jour le premier champ et retire `cle_tri`, ce réglage pourra être passé à `False`.

Il n’y a pas de soustraction fixe de deux heures : le décalage explicite du flux et les règles du fuseau Paris couvrent l’hiver et l’été. Le traitement des heures de l’agenda et de la météo reste indépendant.

## Installation

1. Copier `affichagebusV3_1.py` dans le dossier de l’écran, à côté du dossier `icons/` actuel.
2. Garder les images originales dans ce dossier, notamment le logo JUNIA blanc et `qrcode.png`.
3. Tester depuis la session graphique, avec le même Python que le démarrage automatique :

```bash
python3 affichagebusV3_1.py --windowed --size 1280x720
```

Échap ferme la fenêtre. Pour un test hors réseau avec des données fictives :

```bash
python3 affichagebusV3_1.py --demo --windowed --size 1280x720
```

4. Arrêter l’instance précédente, sauvegarder le script actuellement utilisé et remplacer son contenu par cette version, ou modifier le chemin de lancement vers `affichagebusV3_1.py`.

Exemple si ton démarrage automatique appelle toujours `affichagebusV2.py` :

```bash
cp -n affichagebusV2.py affichagebusV2.avant-v3_1.py
cp affichagebusV3_1.py affichagebusV2.py
```

Si le lancement appelle `affichagebusV3.py`, adapter ces deux noms. Si la sauvegarde existe déjà, `cp -n` la conserve. Relancer ensuite avec ton mécanisme habituel.

Pas de nouvelle dépendance : Python 3.9+, Pygame 2.x, requests et les données de fuseau horaire Europe/Paris.

## Images et aperçus

Le dossier `icons/` n’a pas été transmis : il faut conserver celui qui fonctionne déjà sur ton écran. Aucun logo ni QR code de remplacement n’est fourni. Les aperçus sont des rendus Pygame avec des données fictives et les représentations de secours disponibles en l’absence de tes images ; le QR code et les images météo originaux apparaissent lorsque le script est placé à côté du dossier `icons/`.

Les captures `agenda_1_2.png` et `agenda_1_7.png` montrent la nouvelle page avec un seul événement, avec les deux variantes du bloc de droite. Les captures des autres nombres d’événements et des quatre pages sont également incluses.

## Vérification

- 23 tests réussis, incluant le cas réel du fuseau erroné dans l’API MEL, la présence/absence de `cle_tri`, l’hiver/l’été, minuit, le tri des départs, les réponses invalides, les pannes réseau et les destinations du bloc latéral.
- Contrôle du chargement prioritaire des images météo et de la suppression des deux éléments du pied de page.
- Rendu de l’agenda avec zéro à sept événements, titres longs et pagination ; rendu avec données présentes, absentes ou anciennes en 1920×1080, 1280×720 et 1024×768.
- Correction des horaires contrôlée sur les données réelles de Solférino.
- Vérification visuelle de la grande carte d’événement, des listes/grilles et des deux variantes de la colonne droite.

Tests locaux sur macOS avec pygame-ce 2.5.8. La V3.1 n’a pas été déployée ni mesurée sur le Raspberry Pi. Les fichiers originaux de logo, météo et QR code n’étant pas fournis, leur rendu exact et le scan du QR code restent à vérifier sur place.

Exécution des tests depuis le dossier du script :

```bash
python3 -m unittest -v test_affichagebusV3_1.py
```

Les propositions précédentes (extinction nocturne, supervision, messages prioritaires, administration et cache persistant) ne sont toujours pas implémentées.

