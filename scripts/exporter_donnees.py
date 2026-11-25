"""Exporte un instantané figé des deux sources, pour que l'évaluation soit reproductible.

- Catalogue : modèles de vélos électriques (marque, modèle, année) de l'observatoire (table dbt `dim_modeles`).
- Annonces : vélos électriques d'occasion de buycycle.com (particuliers et pros), un instantané de collecte.

Seules les colonnes utiles au rapprochement sont gardées (pas d'identifiant de vendeur).

Usage :
    python scripts/exporter_donnees.py --base ../observatoire-velo-electrique/data/observatoire.duckdb \
        --annonces ../velo-essentiel-data/data/instantanes/buycycle/date=2026-11-15.parquet
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

RACINE = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base", required=True, type=Path, help="base DuckDB de l'observatoire (table dim_modeles)")
    p.add_argument("--annonces", required=True, type=Path, help="instantané Parquet des annonces buycycle")
    args = p.parse_args()

    sortie = RACINE / "data"
    sortie.mkdir(exist_ok=True)
    with duckdb.connect(str(args.base), read_only=True) as con:
        con.sql(
            """
            select cle_modele, marque, modele, annee_modele, type_velo
            from dim_modeles
            order by marque, modele, annee_modele
            """
        ).write_parquet(str(sortie / "catalogue.parquet"))
        n_cat = con.sql(f"select count(*) from read_parquet('{sortie / 'catalogue.parquet'}')").fetchall()[0][0]

    con = duckdb.connect()
    con.sql(
        f"""
        select distinct on (sku)
            cast(sku as varchar)          as annonce_id,
            nom, marque,
            try_cast(annee as integer)    as annee,
            taille, etat, type,
            try_cast(prix as double)      as prix,
            url,
            cast(date_collecte as date)   as date_collecte
        from read_parquet('{args.annonces}')
        where moteur
        order by sku
        """
    ).write_parquet(str(sortie / "annonces.parquet"))
    n_ann = con.sql(f"select count(*) from read_parquet('{sortie / 'annonces.parquet'}')").fetchall()[0][0]
    print(f"catalogue : {n_cat} modèles-années ; annonces : {n_ann} vélos électriques")


if __name__ == "__main__":
    main()
