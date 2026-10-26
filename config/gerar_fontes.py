"""Gera e valida docs/FONTES.md a partir de config/fontes.yaml.

O catálogo usa deliberadamente JSON legível, subconjunto de YAML 1.2.
Não requer PyYAML nem dependência de rede no CI.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = RAIZ / "config" / "fontes.yaml"
DOCUMENTO = RAIZ / "docs" / "FONTES.md"
ESTADOS = {"real", "parcial", "parado", "so_conector"}
CLASSES = {"OBSERVADO", "INFERIDO", "ESTIMADO", "CONFIRMADO_EXTERNAMENTE"}
OBRIGATORIOS = {
    "id", "nome", "orgao", "url_oficial", "licenca", "url_termos",
    "situacao_licenca", "pode_publicar_no_repositorio", "pode_exportar",
    "frequencia_esperada", "prazo_frescor_horas", "classe_dado",
    "tabela_destino", "estado_atual", "observacao",
}


def carregar() -> dict:
    dados = json.loads(CATALOGO.read_text(encoding="utf-8"))
    if dados.get("versao_catalogo") != 1 or not dados.get("fontes"):
        raise ValueError("Versão ou lista de fontes inválida")
    vistos = set()
    for fonte in dados["fontes"]:
        if not isinstance(fonte, dict) or set(fonte) != OBRIGATORIOS:
            raise ValueError("Esquema de fonte divergente")
        identificador = fonte["id"]
        if not isinstance(identificador, str) or not re.fullmatch(r"[A-Z0-9_]+", identificador):
            raise ValueError("ID de fonte inválido")
        if identificador in vistos:
            raise ValueError("ID duplicado: " + identificador)
        vistos.add(identificador)
        campos_texto = OBRIGATORIOS - {"url_termos", "pode_publicar_no_repositorio",
                                      "pode_exportar", "prazo_frescor_horas"}
        if any(not isinstance(fonte[c], str) or not fonte[c].strip() for c in campos_texto):
            raise ValueError("Campo textual ausente: " + identificador)
        if not fonte["url_oficial"].startswith("https://"):
            raise ValueError("URL oficial deve usar HTTPS")
        if fonte["url_termos"] is not None and (
            not isinstance(fonte["url_termos"], str) or
            not fonte["url_termos"].startswith("https://")
        ):
            raise ValueError("URL de termo inválida")
        if fonte["estado_atual"] not in ESTADOS or fonte["classe_dado"] not in CLASSES:
            raise ValueError("Classe ou estado inválido")
        if type(fonte["prazo_frescor_horas"]) is not int or fonte["prazo_frescor_horas"] <= 0:
            raise ValueError("Frescor deve ser inteiro positivo")
        if type(fonte["pode_exportar"]) is not bool or type(fonte["pode_publicar_no_repositorio"]) is not bool:
            raise ValueError("Permissões devem ser booleanas")
        if fonte["situacao_licenca"] == "pendente" and (
            fonte["pode_exportar"] or fonte["pode_publicar_no_repositorio"]
        ):
            raise ValueError("Não pode liberar redistribuição com licença pendente")
        if fonte["situacao_licenca"] == "identificada" and not fonte["url_termos"]:
            raise ValueError("Licença identificada exige URL de termo")
    cepea = next((x for x in dados["fontes"] if x["id"] == "CEPEA"), None)
    if cepea is None or cepea["licenca"] != "CC BY-NC 4.0" or cepea["pode_exportar"] or cepea["pode_publicar_no_repositorio"]:
        raise ValueError("Proteção CEPEA ausente")
    return dados


def escapar(valor: object) -> str:
    return str(valor).replace("|", r"\|").replace("\n", " ").replace("\r", " ")


def renderizar(dados: dict) -> str:
    linhas = [
        "# NIVON — Catálogo único de fontes", "",
        "_Gerado automaticamente de `config/fontes.yaml`. Não edite este arquivo manualmente._", "",
        "Data do catálogo: " + dados["atualizado_em"] + ".", "",
        dados["semantica_permissoes"], "",
        "Estados: `real`, `parcial`, `parado`, `so_conector`. Os estados foram auditados documentalmente, não por consulta direta ao BigQuery.", "",
        "| ID | Nome e órgão | URL oficial | Licença / termo | Repositório | Exportar | Frequência | Frescor (h) | Classe | Destino planejado | Estado |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for f in dados["fontes"]:
        termo = " ([termo](" + f["url_termos"] + "))" if f["url_termos"] else " (termo a confirmar)"
        linhas.append(
            "| " + escapar(f["id"]) + " | " + escapar(f["nome"]) + " (" + escapar(f["orgao"]) + ")"
            + " | [fonte](" + f["url_oficial"] + ") | " + escapar(f["licenca"]) + termo
            + " | " + ("sim" if f["pode_publicar_no_repositorio"] else "não")
            + " | " + ("sim" if f["pode_exportar"] else "não")
            + " | " + escapar(f["frequencia_esperada"])
            + " | " + str(f["prazo_frescor_horas"])
            + " | " + escapar(f["classe_dado"])
            + " | `" + escapar(f["tabela_destino"]) + "`"
            + " | " + escapar(f["estado_atual"]) + " |"
        )
    linhas.extend([
        "", "## Observações de implantação", "",
        "As tabelas são destinos propostos; `so_conector` não constitui prova de execução ou carga em GCP. O catálogo é inventário de fontes, não autorização de tráfego, scraping, reuso comercial ou redistribuição.", "",
        "Para cada fonte, verifique a licença de seus dados de origem antes de habilitar exportação. A licença MIT do agrobr cobre a biblioteca, não o conteúdo coletado. O status jurídico `pendente` significa bloqueio externo.", "",
        "## Ressalvas por fonte", "",
    ])
    for f in dados["fontes"]:
        linhas.append("- **" + escapar(f["id"]) + ":** " + escapar(f["observacao"]))
    linhas.extend(["", "Validação determinística: `python config/gerar_fontes.py --check`. Regeneração: `python config/gerar_fontes.py`.", ""])
    return "\n".join(linhas)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    esperado = renderizar(carregar())
    if args.check:
        if not DOCUMENTO.is_file() or DOCUMENTO.read_text(encoding="utf-8") != esperado:
            print("FALHA: docs/FONTES.md diverge do catálogo config/fontes.yaml")
            return 1
        print("OK: catálogo, permissões e documentação consistentes")
        return 0
    DOCUMENTO.write_text(esperado, encoding="utf-8")
    print("Gerado:", DOCUMENTO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
