"""Referencias oficiais SIADE observadas em execucao REAL do NIVON em 23/10/2026.

Os 19 manifestos de 2006-2024 foram preservados como artefatos do run
https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39944237120
FONTE: CKAN da ANTT, nao URL adivinhada ou scraping de pagina HTML.

Usar somente com fallback opt-in caso CKAN esteja momentaneamente invalido,
e somente se SHA256 do CSV baixado corresponder ao historico abaixo.
Nao substitui a consulta ao catalogo CKAN para identificar revisoes novas.
"""
from __future__ import annotations

import re
from .transporte_multimodal import ErroTransporte

# ano uuid recurso-CKAN sha256 bruto observado numero de linhas no arquivo
_REGISTROS = """
2006 67965b5b-daee-4b9d-83cd-baff16e5427d 93d1625b763064e76a11ba57ba1f8d90ca20620eaed63dbbd9260b68c0d29c83 11499
2007 bcfcc472-284e-4aff-991b-08d1465a0396 6bb372e271a7eca8db921835cb7f85ade9ce739e45175900d6b724b2e40986f6 11356
2008 9e3335c2-6aab-44ce-90a6-d369eff35a65 5ecd1d56b394e0a67a81bb1001dddc9903e19690d70e2bc95d0dcc1c1d873dfa 10791
2009 e22c7159-7a0d-433f-9f64-9b6138e50d15 c9a6c035757c44818a99fcc448956588c13fbecc7188352a81b4965e8bab6904 10077
2010 5eb5d49c-7bd1-4a7c-85a2-bcb51f3d0cd1 c8197cb3da9a7e123e81b980276d1c61e8468c085532201c9b699b9e886fd48b 9467
2011 780985a0-7b44-430b-b334-8f18d4634b56 79f17b3a2a296e9d40bb5b2a5d724e5575a054e7ab32e9bc2b17b47dce8e19ec 8784
2012 a8735e59-5e9a-4e26-a85d-a8ac4b4ba0c5 b1a8a616420f932066f8be8059c995fc972259efe2f9db29e6193520e3a4eef8 8493
2013 3af9247f-60cf-4598-8c7c-8cb6220ecb38 2c742384b57222bb7d4c62831899428147c6ea2b05877bd0227066eeb1fa41dc 7962
2014 70417d23-57bd-4f0e-9a59-783dcf08f693 f7849831d9abcfe801b2f0972e18f3671ab36dd2665149de37a34dba3322805a 7278
2015 c85e9743-af99-44b1-94ad-230d6d6d9495 ee6675a0cb0517feb91d50d68c8e91ffc390c3e971c2a03dc18cf38d5089494d 7082
2016 3585517d-2a4c-48da-9f54-f1cf12a1e9d4 fd2277c6a0370fa917e85007ef2f888045202840f45b4a21b1ff16559facd792 6962
2017 1d72f99e-9a5e-45c3-b9f4-72898409b4a3 7ab9641ce13d40b7be8a8f4d4f098dd98f6a50501073ee86d5173d 7139
2018 ff4dce38-bdb4-43ab-8d64-7b9ad0936e52 93f6cbc032479fbb141acd7aa11ed6f55428ffff9f944f89ea843bb1a747aa80 7598
2019 052db0cf-13fa-4d47-8b28-034e079b6b18 d8b95d12da135fda7717e02b3f3742d06a849ff2879a7355b54a3bb451d789ea 7965
2020 5e5e8507-aadc-4c9e-a654-237f1c9ef3aa fc0fd03dd61c62db50c50b8cd286fb3250deb0cf00807592e6c2f37ded562eff 7748
2021 1fa04c4d-dde4-416a-b794-9006b6cf5df1 08d37a3d8224c9ef6d7368bc213d98282a19d48714bebab999f36d8db213f3cd 7955
2022 9a823c7c-0a07-43e5-ba66-e6305fe51138 2771a886016599a0c9988acf089cba4f9c7a0758c6d7092390ac601bec58426a 7972
2023 758da4ad-5546-4051-96fd-29fdc5a4076e e82ccde481d0d3b385b11dfc932a49e03eedb0f4f03f7d0dba4112f3c8d6122e 7928
2024 c32ca914-0aa3-4282-b92a-6eb4200c5033 5f596d970ca568679b1db2962f82b92b21e39ad9f6fe871137613d4dcf7a0673 7911
""".strip()

DADOS = {}
for _linha in _REGISTROS.splitlines():
    _ano, _id, _sha, _registros = _linha.split()
    _ano, _registros = int(_ano), int(_registros)
    if (_ano in DADOS or not re.fullmatch(r"[0-9a-f-]{36}", _id)
            or not re.fullmatch(r"[0-9a-f]{64}", _sha)
            or _registros <= 0):
        raise RuntimeError("manifesto historico ANTT prevalidado adulterado")
    _url = (
        "https://dados.antt.gov.br/dataset/438a5184-09db-49a3-88c8-0bad418b4409/"
        + f"resource/{_id}/download/producao_origem_destino_{_ano}.csv")
    DADOS[_ano] = {"url":_url, "id":_id, "sha_anterior":_sha,
                   "registros_anteriores":_registros,
                   "origem_evidencia":"GITHUB_ACTIONS_39944237120_CKAN_ANTT"}


def referencia_antt_verificada(ano: int) -> dict:
    if type(ano) is not int or ano not in DADOS:
        raise ErroTransporte("ano ANTT sem URL/SHA historico validado")
    return DADOS[ano].copy()
