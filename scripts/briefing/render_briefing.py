"""Renderiza o modelo visual aprovado usando dados da edição em JSON.

Uso: python scripts/briefing/render_briefing.py templates/briefing/edicao_exemplo_2026-10-21.json briefing.pdf
Dependências: pip install Jinja2 WeasyPrint
Não coleta preços, não valida fontes e não publica no WhatsApp.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from weasyprint import HTML

ROOT = Path(__file__).resolve().parents[2]


def pairs(items):
    return [
        [items[i], items[i + 1] if i + 1 < len(items) else None]
        for i in range(0, len(items), 2)
    ]


def validate(data):
    edition = data.get("edition", {})
    for key in ("date_label", "closing_label", "sources_note"):
        if not edition.get(key):
            raise ValueError(f"Campo obrigatório ausente: edition.{key}")
    if not data.get("market_groups") or not data.get("news"):
        raise ValueError("Cotações e notícias são obrigatórias")
    freight = data.get("freight", {})
    if len(freight.get("main", [])) != 3 or len(freight.get("additional", [])) != 3:
        raise ValueError("Esperados três corredores principais e três complementares")
    for group in data["market_groups"]:
        for row in group["items"]:
            if row.get("direction") not in ("up", "down", "flat", "missing"):
                raise ValueError("direction inválido: up/down/flat/missing")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dados_json", type=Path)
    parser.add_argument("saida_pdf", type=Path)
    args = parser.parse_args()
    data = validate(json.loads(args.dados_json.read_text(encoding="utf-8")))
    env = Environment(
        loader=FileSystemLoader(str(ROOT / "templates" / "briefing")),
        autoescape=True,
        undefined=StrictUndefined
    )
    html = env.get_template("modelo_visual.html").render(
        edition=data["edition"],
        market_pairs=pairs(data["market_groups"]),
        freight=data["freight"],
        news_pairs=pairs(data["news"]),
    )
    args.saida_pdf.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(ROOT)).write_pdf(str(args.saida_pdf))
    print(f"PDF gerado: {args.saida_pdf}")
    print("Texto separado para WhatsApp:\n" + data.get("whatsapp_intro", ""))


if __name__ == "__main__":
    main()
