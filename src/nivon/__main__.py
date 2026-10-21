"""Demonstração sintética e local, sem chamadas a serviços externos."""
import json
from .motores import CEPEA, projetar_consumo, verificar_teto_materia_seca


def main():
    resultado = {
        "aviso": "DADOS TOTALMENTE SINTETICOS — NAO UTILIZAR COMO OBSERVADOS",
        "cenario_consumo": projetar_consumo({2020: 78, 2021: 80, 2022: 76.8, 2023: 82.2}, 2, 3),
        "cepea_finalidade": CEPEA.finalidade,
        "cepea_teto_exemplo": verificar_teto_materia_seca(
            umidade_milho=0.14, umidade_ddg=0.11, tipo_etanol="HIDRATADO"),
    }
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
