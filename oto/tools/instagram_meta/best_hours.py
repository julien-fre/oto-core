"""Meilleures heures et jours de publication — un calcul LOCAL, sur du déjà lu.

Meta n'expose pas cette réponse : on la dérive de l'engagement moyen (likes +
commentaires) des publications déjà récupérées. C'est donc une **heuristique**,
et elle est nommée comme telle jusque dans ce qu'elle rend : `sample_size` voyage
avec le résultat, parce qu'un classement sur quatre posts et un classement sur
quarante se lisent de la même façon et ne valent pas la même chose.

Aucun appel réseau ici — la fonction prend la liste de médias que l'appelant a
lue, ce qui la rend testable sans rien simuler et évite un second aller-retour
quand l'appelant a déjà les publications sous la main.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

#: Lundi = 0, comme `datetime.weekday()`.
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def compute_best_hours(media: list[dict]) -> dict:
    """`{by_hour, by_weekday, sample_size}`, triés par engagement moyen décroissant.

    Les heures sont celles des horodatages rendus par Meta (UTC) : les convertir
    demanderait de savoir dans quel fuseau publie le compte, ce que l'API ne dit
    pas — et une conversion supposée décalerait le classement d'une ou deux heures
    sans que rien ne le signale.

    Une publication sans horodatage est IGNORÉE et ne compte pas dans les moyennes,
    mais reste dans `sample_size` : c'est le nombre de publications examinées, pas
    le nombre de retenues — un écart entre les deux se voit alors en comparant les
    `posts` cumulés, au lieu d'être effacé."""
    if not media:
        return {"by_hour": [], "by_weekday": [], "sample_size": 0}

    par_heure: dict[int, dict[str, int]] = defaultdict(lambda: {"total": 0, "count": 0})
    par_jour: dict[int, dict[str, int]] = defaultdict(lambda: {"total": 0, "count": 0})

    for m in media:
        horodatage = m.get("timestamp")
        if not horodatage:
            continue
        try:
            dt = datetime.fromisoformat(str(horodatage).replace("Z", "+00:00"))
        except ValueError:
            continue
        engagement = (m.get("like_count") or 0) + (m.get("comments_count") or 0)
        par_heure[dt.hour]["total"] += engagement
        par_heure[dt.hour]["count"] += 1
        par_jour[dt.weekday()]["total"] += engagement
        par_jour[dt.weekday()]["count"] += 1

    return {
        "by_hour": _classe(par_heure, "hour", lambda h: h),
        "by_weekday": _classe(par_jour, "weekday", lambda wd: JOURS[wd]),
        "sample_size": len(media),
    }


def _classe(compteurs: dict, cle: str, libelle) -> list[dict[str, Any]]:
    return sorted(
        ({cle: libelle(k), "avg_engagement": round(v["total"] / v["count"]),
          "posts": v["count"]}
         for k, v in compteurs.items()),
        key=lambda x: -x["avg_engagement"])
