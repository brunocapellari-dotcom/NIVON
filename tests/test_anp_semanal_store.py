import sqlite3
import unittest
import hmac
import json
from datetime import timedelta
from hashlib import sha256
from copy import deepcopy

from nivon.anp_atestacoes import DOMAIN_PREFIX, ErroAtestacaoANP
from nivon.anp_semanal_store import _observacoes, _tempo
from nivon.anp_indice_lpc import URL_INDICE

from nivon.anp_semanal_store import (
    ErroANPOficial, consultar_preco_semanal,
    gravar_edicao_semanal, inicializar_store_anp,
)


KEYS = {
    "DIREITOS_USO": {"chave": b"fixture-rights-authority-00000000000000001",
                    "emissor": "fake-rights-reviewer"},
    "HOMOLOGACAO_LAYOUT": {"chave": b"fixture-layout-authority-0000000000000001",
                           "emissor": "fake-layout-reviewer"},
}


def assinar_autorizacao(r, pub, rights_sha="c"*64, indice_sha="9"*64):
    linhas = _observacoes(r, _tempo(pub, "pub"))
    digest = sha256(json.dumps(
        linhas, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()).hexdigest()
    instante = _tempo(r["coletado_em"], "coleta")
    ass = {}
    for dominio, autoridade in KEYS.items():
        campos = dict(
            versao=1, edicao_sha256=r["sha256"], resumo_sha256=digest,
            origem_url=r["url_origem"], publicado_em=_tempo(pub, "pub").isoformat(),
            prova_publicacao_sha256="b"*64,
            prova_direitos_sha256=rights_sha, indice_sha256=indice_sha,
            operacao="ARMAZENAMENTO_ANALITICO_NAO_COMERCIAL",
            publicavel=False,
            dominio=dominio, emissor_id=autoridade["emissor"],
            aprovacao_id=f"test-{dominio}-{r['sha256'][:16]}",
            emitido_em=(instante-timedelta(hours=2)).isoformat(),
            valido_ate=(instante+timedelta(days=2)).isoformat(),
        )
        payload = json.dumps(campos, sort_keys=True, ensure_ascii=True,
                             separators=(",", ":")).encode()
        campos["assinatura_hmac_sha256"] = hmac.new(
            autoridade["chave"], DOMAIN_PREFIX + dominio.encode("ascii")
            + b"\x00" + payload, sha256,
        ).hexdigest()
        ass[dominio] = campos
    return ass


def indice_real(r, coleta="2026-10-20T14:00:00+00:00"):
    return dict(sha256="9"*64, coletado_em=coleta,
                indice_url=URL_INDICE, url_no_indice=r["url_origem"])


def resumo(sha="a"*64, preco=5.85, semana="2026-10-17",
           coleta="2026-10-20T15:00:00+00:00"):
    return {
        "dataset_id": "ANP_PRECO_REVENDA_DIESEL",
        "fonte": "ANP_RESUMO_LPC_SEMANAL",
        "sha256": sha, "coletado_em": coleta,
        "url_origem": "https://www.gov.br/anp/pt-br/assuntos/precos/arquivos-lpc/teste.xlsx",
        "publicavel": False,
        "observacoes": [{
            "uf": "MT", "municipio": "SORRISO", "produto": "DIESEL S10",
            "semana_inicio_oficial": "2026-10-11",
            "semana_fim_oficial": semana,
            "preco_medio_revenda_rs_l": preco,
            "postos_pesquisados": 8,
            "natureza": "MEDIA_AMOSTRAL_REVENDA_MUNICIPIO_ANP_SEMANA_OFICIAL",
        }],
    }


class TestANPSemanalStore(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        inicializar_store_anp(self.db)

    def tearDown(self):
        self.db.close()

    def grava(self, r=None, *, classe="SINTETICO",
              pub="2026-10-19T12:00:00+00:00", **kwargs):
        entrada = r if r is not None else resumo()
        # Credenciais são fictícias e existem somente nesta classe de teste.
        # Casos negativos sem "direitos_confirmados" NÃO recebem aprovação.
        if classe == "REAL_AUTORIZADO" and kwargs.get("direitos_confirmados") is True:
            kwargs.setdefault("prova_direitos_sha", "c"*64)
            kwargs.setdefault("habilitacao_real", True)
            kwargs.setdefault("verificado_em_confiavel", (
                _tempo(entrada["coletado_em"], "coleta")
                + timedelta(minutes=30)).isoformat())
            kwargs.setdefault("indice_evidencia", indice_real(entrada))
            kwargs.setdefault("autoridades_confiaveis", KEYS)
            kwargs.setdefault("aprovacoes_assinadas", assinar_autorizacao(
                entrada, pub, kwargs.get("prova_direitos_sha", "c"*64)))
            kwargs.setdefault("ids_revogados", frozenset())
        return gravar_edicao_semanal(
            self.db, resumo=entrada, data_publicacao=pub,
            prova_publicacao_sha="b"*64,
            classe=classe, **kwargs,
        )

    def consulta(self, **kw):
        params = dict(municipio="SORRISO", produto="DIESEL S10", uf="MT",
                      as_of="2026-10-20T17:00:00+00:00")
        params.update(kw)
        return consultar_preco_semanal(self.db, **params)

    def test_relogio_do_controlador_obrigatorio_e_nao_retroativo(self):
        entrada = resumo()
        with self.assertRaisesRegex(PermissionError,"instante confiável"):
            self.grava(
                r=entrada, classe="REAL_AUTORIZADO",
                direitos_confirmados=True, verificado_em_confiavel=None)
        with self.assertRaisesRegex(PermissionError,"preceder a captura"):
            self.grava(
                r=entrada, classe="REAL_AUTORIZADO",
                direitos_confirmados=True,
                verificado_em_confiavel="2026-10-19T12:00:00+00:00")
        with self.assertRaisesRegex(ErroAtestacaoANP,"expirada"):
            self.grava(
                r=entrada, classe="REAL_AUTORIZADO",
                direitos_confirmados=True,
                verificado_em_confiavel="2026-10-30T12:00:00+00:00")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0],0)

    def test_aprovacoes_duplas_autenticadas_sao_obrigatorias(self):
        r = resumo()
        provas = assinar_autorizacao(r, "2026-10-19T12:00:00+00:00")
        for kwargs in (
            {"habilitacao_real":False},
            {"aprovacoes_assinadas":{}},
            {"autoridades_confiaveis":{}},
            {"ids_revogados":None},
            {"indice_evidencia":None},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PermissionError):
                self.grava(
                    classe="REAL_AUTORIZADO", direitos_confirmados=True,
                    prova_direitos_sha="c"*64, **kwargs,
                )
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0],0)

    def test_prova_nao_autenticada_nao_satisfaz_revisor(self):
        r=resumo()
        assinatura=assinar_autorizacao(r,"2026-10-19T12:00:00+00:00")
        assinatura["DIREITOS_USO"]["origem_url"]="https://www.gov.br/anp/outro.xlsx"
        with self.assertRaisesRegex(ErroAtestacaoANP,"vinculada"):
            self.grava(classe="REAL_AUTORIZADO",direitos_confirmados=True,
                       prova_direitos_sha="c"*64,
                       aprovacoes_assinadas=assinatura)
        self.assertEqual(self.consulta()["status"],"SEM_EDICAO_REAL_ASOF")

    def test_registro_falso_de_assinaturas_sem_chaves_confiaveis_bloqueia(self):
        entrada=resumo()
        falso=assinar_autorizacao(entrada,"2026-10-19T12:00:00+00:00")
        falso["HOMOLOGACAO_LAYOUT"]["assinatura_hmac_sha256"]="f"*64
        with self.assertRaisesRegex(ErroAtestacaoANP,"assinatura"):
            self.grava(classe="REAL_AUTORIZADO",direitos_confirmados=True,
                       aprovacoes_assinadas=falso)
        self.assertEqual(self.consulta()["status"],"SEM_EDICAO_REAL_ASOF")

    def test_assinatura_tem_escopo_apenas_analise_nao_comercial(self):
        entrada=resumo()
        for campo, valor in (("operacao","PUBLICACAO_EXTERNA"),
                              ("publicavel",True), ("indice_sha256","f"*64),
                              ("prova_publicacao_sha256","f"*64)):
            docs=assinar_autorizacao(entrada,"2026-10-19T12:00:00+00:00")
            docs["DIREITOS_USO"][campo]=valor
            with self.subTest(campo=campo), self.assertRaisesRegex(
                    ErroAtestacaoANP,"vinculada"):
                self.grava(classe="REAL_AUTORIZADO",
                           direitos_confirmados=True,
                           aprovacoes_assinadas=docs)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0],0)

    def test_mesmo_id_aprovacao_nao_e_reutilizavel_em_edicao_diferente(self):
        primeira=resumo()
        segunda=resumo(sha="d"*64,preco=5.91)
        self.grava(r=primeira,classe="REAL_AUTORIZADO",
                   direitos_confirmados=True)
        docs=assinar_autorizacao(segunda,"2026-10-19T12:00:00+00:00")
        for dominio in docs:
            docs[dominio]["aprovacao_id"] = f"test-{dominio}-"+primeira["sha256"][:16]
            unsigned={k:v for k,v in docs[dominio].items()
                      if k!="assinatura_hmac_sha256"}
            serializado=json.dumps(unsigned,sort_keys=True,ensure_ascii=True,
                                   separators=(",",":")).encode()
            docs[dominio]["assinatura_hmac_sha256"]=hmac.new(
                KEYS[dominio]["chave"],DOMAIN_PREFIX+dominio.encode()
                +bytes([0])+serializado,sha256
            ).hexdigest()
        with self.assertRaises(sqlite3.IntegrityError):
            self.grava(r=segunda,classe="REAL_AUTORIZADO",
                       direitos_confirmados=True,aprovacoes_assinadas=docs)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0],1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_atestacoes").fetchone()[0],2)

    def test_mutacao_de_preco_sha_ou_direitos_falha(self):
        for mudança in ("preco","sha","direitos"):
            entrada=resumo()
            aprovacoes=assinar_autorizacao(entrada,"2026-10-19T12:00:00+00:00")
            kwargs={}
            if mudança=="preco":
                entrada["observacoes"][0]["preco_medio_revenda_rs_l"]=9.99
            elif mudança=="sha":
                entrada["sha256"]="a"*63+"0"
            else:
                kwargs["prova_direitos_sha"]="e"*64
            with self.subTest(tipo=mudança), self.assertRaisesRegex(
                    ErroAtestacaoANP,"vinculada"):
                self.grava(r=entrada,classe="REAL_AUTORIZADO",
                           direitos_confirmados=True,
                           aprovacoes_assinadas=aprovacoes,**kwargs)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0],0)

    def test_revogacao_chaves_iguais_emissores_iguais_e_expiracao(self):
        entrada=resumo()
        docs=assinar_autorizacao(entrada,"2026-10-19T12:00:00+00:00")
        revogado=docs["DIREITOS_USO"]["aprovacao_id"]
        with self.assertRaisesRegex(ErroAtestacaoANP,"revogado"):
            self.grava(classe="REAL_AUTORIZADO",direitos_confirmados=True,
                       ids_revogados=frozenset({revogado}))
        confianca={d: dict(val) for d,val in KEYS.items()}
        confianca["HOMOLOGACAO_LAYOUT"]["chave"]=confianca["DIREITOS_USO"]["chave"]
        with self.assertRaisesRegex(ErroAtestacaoANP,"segregação"):
            self.grava(classe="REAL_AUTORIZADO",direitos_confirmados=True,
                       autoridades_confiaveis=confianca)
        docs["DIREITOS_USO"]["valido_ate"]="2026-10-19T13:00:00+00:00"
        with self.assertRaises(ErroAtestacaoANP):
            self.grava(classe="REAL_AUTORIZADO",direitos_confirmados=True,
                       aprovacoes_assinadas=docs)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_atestacoes").fetchone()[0],0)

    def test_leitura_legada_sem_atestacao_e_invisivel(self):
        self.db.execute("""INSERT INTO anp_semanal_edicoes
            (sha,fonte_url,classe,data_publicacao,prova_publicacao_sha,
            prova_direitos_sha,resumo_sha) VALUES (?,?,?,?,?,?,?)""",
            ("f"*64,resumo()["url_origem"],"REAL_AUTORIZADO",
             "2026-10-19T12:00:00+00:00","b"*64,"c"*64,"a"*64))
        self.db.execute("""INSERT INTO anp_semanal_capturas
            (sha,data_coleta) VALUES (?,?)""",
            ("f"*64,"2026-10-20T15:00:00+00:00"))
        self.db.execute("""INSERT INTO anp_semanal_observacoes
            (sha,uf,municipio,produto,semana_inicio,semana_fim,preco_medio,postos)
            VALUES (?,?,?,?,?,?,?,?)""",
            ("f"*64,"MT","SORRISO","DIESEL S10","2026-10-11",
             "2026-10-17","6.8",12))
        self.db.commit()
        self.assertEqual(self.consulta()["status"],"SEM_EDICAO_REAL_ASOF")

    def test_guardar_duas_evidencias_e_reusar_sem_recriar(self):
        self.grava(classe="REAL_AUTORIZADO",direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        self.grava(classe="REAL_AUTORIZADO",direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        evidencias=self.db.execute(
            "SELECT dominio,emissor_id FROM anp_semanal_atestacoes ORDER BY dominio"
        ).fetchall()
        self.assertEqual(len(evidencias),2)
        self.assertNotEqual(evidencias[0][1],evidencias[1][1])

    def test_sintetico_nao_vira_real_ou_publicavel(self):
        self.assertFalse(self.grava()["fonte_publicavel"])
        self.assertEqual(self.consulta()["status"], "SEM_EDICAO_REAL_ASOF")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 1)

    def test_idempotencia_e_coletas_separadas(self):
        self.assertTrue(self.grava()["captura_nova"])
        self.assertFalse(self.grava()["captura_nova"])
        mais = resumo(coleta="2026-10-20T16:00:00+00:00")
        self.assertTrue(self.grava(r=mais)["captura_nova"])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_capturas").fetchone()[0], 2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_observacoes").fetchone()[0], 1)

    def test_publicacao_e_coleta_independentes_no_asof(self):
        self.grava(classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        self.assertEqual(self.consulta(
            as_of="2026-10-18T20:00:00+00:00")["status"], "SEM_EDICAO_REAL_ASOF")
        self.assertEqual(self.consulta(
            as_of="2026-10-19T20:00:00+00:00")["status"], "SEM_EDICAO_REAL_ASOF")
        item = self.consulta()
        self.assertEqual(item["status"], "AMOSTRA_HISTORICA_PIT")
        self.assertEqual(item["preco_medio_revenda_brl_l"], "5.85")
        self.assertEqual(item["semana_fim_oficial"], "2026-10-17")
        self.assertFalse(item["publicavel"])
        self.assertEqual(item["primeira_coleta"], "2026-10-20T15:00:00+00:00")
        self.assertNotIn("frete", item["classe"].lower().replace("nao_frete",""))

    def test_revisao_entre_edicoes_nao_substitui_preco_implicitamente(self):
        self.grava(classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        novo = resumo(sha="d"*64, preco=5.90)
        novo["coletado_em"] = "2026-10-20T18:00:00+00:00"
        self.grava(r=novo, classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="e"*64)
        self.assertEqual(self.consulta()["status"], "AMOSTRA_HISTORICA_PIT")
        self.assertEqual(self.consulta(
            as_of="2026-10-21T00:00:00+00:00")["status"], "REVISOES_CONFLITANTES")
        self.assertFalse(self.consulta(
            as_of="2026-10-21T00:00:00+00:00")["publicavel"])

    def test_semana_vencida_nao_e_cotacao_atual(self):
        self.grava(classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        self.assertEqual(self.consulta(
            as_of="2026-12-01T00:00:00+00:00")["status"], "DADO_VENCIDO")

    def test_sem_direitos_nao_grava_fonte_real(self):
        with self.assertRaises(PermissionError):
            self.grava(classe="REAL_AUTORIZADO")
        with self.assertRaises(ErroANPOficial):
            self.grava(direitos_confirmados=True)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_conflito_mesmo_sha_nao_muda_historico(self):
        self.grava()
        dif = resumo(preco=6.5)
        with self.assertRaisesRegex(ErroANPOficial, "mesmo SHA"):
            self.grava(r=dif)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_capturas").fetchone()[0], 1)

    def test_datas_de_publicacao_e_serie_incorretas(self):
        with self.assertRaises(ErroANPOficial):
            self.grava(pub="2026-10-21T12:00:00+00:00")
        with self.assertRaises(ErroANPOficial):
            self.grava(pub="2026-10-19T12:00:00")
        with self.assertRaises(ErroANPOficial):
            self.grava(r=resumo(semana="2026-11-17"))
        with self.assertRaises(ErroANPOficial):
            self.grava(r=resumo(coleta="2026-10-18T12:00:00+00:00"))

    def test_duplicatas_e_campos_adversariais(self):
        for change in [
            {"produto": "GASOLINA"},
            {"preco_medio_revenda_rs_l": -1},
            {"preco_medio_revenda_rs_l": float("nan")},
            {"preco_medio_revenda_rs_l": True},
            {"postos_pesquisados": 0},
            {"semana_inicio_oficial": "2026-10-12"},
            {"municipio": ""},
            {"natureza": "DIESEL_PRECO_CONTRATADO"},
        ]:
            r = resumo()
            r["observacoes"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ErroANPOficial):
                self.grava(r=r)
        dup = resumo()
        dup["observacoes"].append(deepcopy(dup["observacoes"][0]))
        with self.assertRaisesRegex(ErroANPOficial, "repetida"):
            self.grava(r=dup)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM anp_semanal_edicoes").fetchone()[0], 0)

    def test_edição_não_confunde_com_csv_mensal(self):
        r = resumo()
        r["fonte"] = "ANP_SERIE_ABERTA_PRECOS_DIESEL"
        with self.assertRaises(ErroANPOficial):
            self.grava(r=r)

    def test_uf_produto_e_municipio_nao_intercambiam(self):
        self.grava(classe="REAL_AUTORIZADO", direitos_confirmados=True,
                   prova_direitos_sha="c"*64)
        self.assertEqual(self.consulta(produto="DIESEL")["status"], "SEM_EDICAO_REAL_ASOF")
        self.assertEqual(self.consulta(uf="GO")["status"], "SEM_EDICAO_REAL_ASOF")
        self.assertEqual(self.consulta(municipio="SINOP")["status"], "SEM_EDICAO_REAL_ASOF")


if __name__ == "__main__":
    unittest.main()
