"""IVO — plano de aquisição pontual para uma errata PAM conhecida.

Distingue aviso público, JSON SIDRA ATUAL e bytes históricos ANTERIORES.
Não preenche lacunas de forma fictícia, não executa rede, não assume que
FTP histórico de 2016 contém a PAM 2021 municipal pré-errata.
"""
from __future__ import annotations
from datetime import date

from .ivo_radar_erratas_pam import radar_erratas_pam
from .sidra_pam import planejar_pam_1612
from .ivo_pam_semantica import conferir_semantica_pam_1612


FTP_PAM_HISTORICO=("https://ftp.ibge.gov.br/Producao_Agricola/"
 "Producao_Agricola_Municipal_%5Banual%5D/")
FTP_LSPA_HISTORICO=("https://ftp.ibge.gov.br/Producao_Agricola/"
 "Levantamento_Sistematico_da_Producao_Agricola_%5Bmensal%5D/Tabelas_xls/")


def plano_evidencias_errata_pam(*,catalogo:dict,municipio_ibge:str,
        ano:int,categoria_c81:str,variavel:str,corte:date)->dict:
    radar=radar_erratas_pam(catalogo=catalogo,
        municipio_ibge=municipio_ibge,ano=ano,
        categoria_c81=categoria_c81,variavel=variavel,corte=corte)
    sem=conferir_semantica_pam_1612(
        variavel=variavel,categoria_c81=categoria_c81,unidade="Toneladas")
    consulta=planejar_pam_1612(
        municipio_ibge=municipio_ibge,ano=ano,
        codigo_produto_c81=categoria_c81,codigo_variavel=variavel)
    tarefas=[]
    for notice in radar["erratas"]:
        aviso=notice["aviso_ja_publicado_no_corte"]
        tarefas.append({
            "errata_id":notice["id"],"aviso_em":notice["aviso_em"],
            "tarefas":[
              {
                "id":"AVISO_DOCUMENTAL",
                "url":notice["fonte_url"],
                "estado":"REFERENCIA_PUBLICA_IDENTIFICADA" if aviso else "INVISIVEL_NO_CORTE",
                "acao":"identificar URL exata do documento/nota oficial e arquivar bytes originais",
                "bytes_verificados":False,
                "tipo":"PORTAL_ERRAMOS_NAO_E_PDF",
              },
              {
                "id":"SIDRA_ESTADO_ATUAL",
                "url":consulta["url"] if aviso else None,
                "estado":"PENDENTE_COLETA_COM_DIREITOS" if aviso else "BLOQUEADO_POR_DATA",
                "acao":"baixar uma consulta pontual SOMENTE se fonte/autorizacoes liberadas; valor atual nao e a vintage anterior",
                "bytes_verificados":False,
                "tipo":"SIDRA_JSON_PONTUAL",
              },
              {
                "id":"SIDRA_ANTES_DA_ERRATA",
                "url":None,
                "estado":"ARQUIVO_HISTORICO_ORIGINAL_NAO_LOCALIZADO",
                "acao":"procurar snapshot datado e verificavel anterior ao aviso; nao recompor valor original do dado atual",
                "bytes_verificados":False,
                "tipo":"VERSAO_ANUAL_MUNICIPAL_PRE_AVISO",
              },
            ]
        })
    return {
        "estado":"PLANO_DE_CAPTURA_SEM_OPERACAO_REMOTA",
        "alvo":{"municipio_ibge":municipio_ibge,"ano_civil":ano,
                "produto":sem["produto"],"indicador":sem["indicador"],
                "unidade":sem["unidade"],"categoria_c81":categoria_c81,
                "variavel_sidra":variavel},
        "corte":corte.isoformat(),
        "avisos":len(radar["erratas"]),"tarefas":tarefas,
        "pesquisa_complementar":[
            {"url":FTP_PAM_HISTORICO,
             "papel":"DIRETORIO_DE_PAM_ANUAL_LEGADA",
             "comprovacao_vintage_2021":False,
             "nota":"Index publico identificado; arquivos por ano no trecho historico examinado nao garantem snapshot anterior a errata de 2026."},
            {"url":FTP_LSPA_HISTORICO,
             "papel":"ARQUIVO_DE_BOLETINS_LSPA_MENSAIS",
             "comprovacao_vintage_2021":False,
             "nota":"Existem arquivos historicos LSPA, mas series de estimativas mensais nao substituem PAM municipal anual."},
        ],
        "licenca_e_coleta_aprovadas_neste_plano":False,
        "valores_anteriores_recuperados":False,
        "arquivos_numericos_baixados":False,
        "homologacao_do_modelo":False,
    }
