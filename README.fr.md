[English](README.md) · **Français**

# Roulette of Legends

La roulette de League of Legends : un rôle et un champion au hasard, seul ou en groupe, suivis dans le client LoL jusqu'au résultat.

## Télécharger

Les deux applis sont sur la page des [releases](https://github.com/Raktos1030/Roulette-of-Legends/releases/latest) :

| | Windows | Mac (Apple Silicon) |
|---|---|---|
| **Roulette of Legends Lite** : la roulette, reliée à LoL | `Roulette-of-Legends-Lite-Setup.exe` | `Roulette-of-Legends-Lite-mac.dmg` |
| **Roulette of Legends** : la version complète | `Roulette-of-Legends-Setup.exe` | bientôt |

Windows : lance l'installeur. Mac : ouvre le .dmg et glisse l'appli dans Applications ; au premier lancement, Réglages Système › Confidentialité et sécurité › « Ouvrir quand même ».

Les nouvelles versions s'installent depuis l'appli : un bandeau apparaît avec un bouton **Mettre à jour**, et ton historique et tes réglages sont conservés.

Les applis sont en français et en anglais.

## Les deux applis

| | Lite | Complète |
|---|:---:|:---:|
| Roulette solo et de groupe (jusqu'à 5 joueurs), mode chaos | ✓ | ✓ |
| Roulette officielle (tout au hasard) ou perso (favoris, rôle ou champion choisi), en un clic | ✓ | ✓ |
| Favoris (rôles et champions) | ✓ | ✓ |
| Classeur : une carte par champion et par poste, gagnée en jouant tes tirages officiels ; parcours de récompenses, skins de roulette | ✓ | ✓ |
| Tirage suivi dans le client : autofill, ban ou champion pris détectés | ✓ | ✓ |
| Historique des parties, résultats et LP | ✓ | ✓ |
| Fiche de jeu pour chaque champion à chaque poste | | ✓ |
| Runes, sorts d'invocateur et set d'objets importés dans LoL | | ✓ |
| Build random (runes, sorts, objets, ordre des sorts), importé dans LoL | | ✓ |
| Overlay en jeu : fiche, stats, écart d'or, sort à monter sur le HUD | | ✓ |
| Page Partie : les deux équipes, leurs classements | | ✓ |

Les applis lisent le client LoL et ne jouent jamais à ta place : aucun pick, ban, verrouillage ni message. Les seules écritures (version complète, réglables) sont ta page de runes, tes sorts d'invocateur et un set d'objets, une fois ton champion verrouillé.

Chaque lancement envoie un comptage anonyme (édition, version, Windows ou Mac), sans cookie ni identifiant ; il se coupe dans Réglages. Le site compte ses visites de la même façon.

## Depuis le code

Python 3.11 :

```
pip install -r requirements.txt
python roulette_lol.py
```

- `python roulette_lol.py --check` : vérifie que chaque combinaison champion + rôle a sa fiche.
- `python packaging/build.py full|lite` : fabrique une appli et son archive dans `_release/`.
- `site/` : la roulette en version site (statique), régénérée par `python site/build_site.py`.

## Sources

Statistiques : lolalytics.com et u.gg (Émeraude+). Noms, sorts et illustrations : Data Dragon (Riot Games). Profils de champions : Meraki Analytics. Polices : Marcellus SC et Cinzel (licence OFL).

---

Roulette of Legends n'est pas approuvée par Riot Games et ne reflète pas les opinions de Riot Games ni de quiconque officiellement impliqué dans la production ou la gestion des propriétés de Riot Games. Riot Games et toutes les propriétés associées sont des marques commerciales ou déposées de Riot Games, Inc.
