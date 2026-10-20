import unittest
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
from hashlib import sha256

from nivon.historico import Observacao
from nivon.ivo_elegibilidade_rotulos import (
    AtestacaoResultado, ErroElegibilidade, avaliar_elegibilidade,
    hash_observacao, serie_elegivel_experimental,
)

UTC=timezone.utc
H=sha256(b"fixture_ivo_trainability").hexdigest()
P=sha256(b"two_independent_reviews").hexdigest()
CORTE=datetime(2026,10,20,14,tzinfo=UTC)


def observacao(mes, *, natureza="OBSERVADO", valor=100., revisao=False):
    # Labels com edicao vinculada ao hash de origem; nunca baixar fontes.
    publicado=date(2025,mes%12+1,5)
    coletado=datetime(2025,mes%12+1,6,12,tzinfo=UTC)
    if revisao:
        publicado=date(2026,1,7)
        coletado=datetime(2026,1,8,12,tzinfo=UTC)
    return Observacao(
        fonte="CONAB",variavel="PRODUCAO",produto="SOJA",regiao="MT",
        unidade="t",calendario="MENSAL",competencia=f"2025-{mes:02d}",
        referencia=date(2025,mes,1),publicacao=publicado,coleta=coletado,
        natureza=natureza,valor=valor,edicao=H if not revisao else "b"*64,
    )


def certificado(mes, *, modo="SINTETICO", natureza="OBSERVADO", classe="MEDICAO_OBSERVADA",
                valor=100., revisao=False, operacoes=None, **extras):
    o=observacao(mes,natureza=natureza,valor=valor,revisao=revisao)
    d=dict(
        observacao=o,dataset_id="TESTE_CONAB_SERIE" if modo=="SINTETICO" else "CONAB_SAFRAS",
        arquivo_sha256=o.edicao,observacao_sha256=hash_observacao(o),
        classe_origem=classe,politica_resultado=classe,modalidade=modo,
        revisores=("REVISOR_UM","REVISOR_DOIS"),autor_modelo="PESQUISADOR",
        parecer_sha256=P,direitos_ref="LICENCA_TESTE_001",
        operacoes_aprovadas=operacoes if operacoes is not None else
            frozenset(("ARMAZENAMENTO","ANALISE","TREINAMENTO")),
        aprovado_em=datetime(2026,2,1,12,tzinfo=UTC),
    )
    d.update(extras)
    return AtestacaoResultado(**d)


def pacote(*, modo="SINTETICO"):
    return [certificado(i,modo=modo) for i in range(1,7)]


class TestIVOElegibilidadeRotulos(unittest.TestCase):
    def test_experimento_sintetico_exige_flag_explicita(self):
        x=avaliar_elegibilidade(pacote(),corte=CORTE)
        self.assertEqual(x["estado"],"BLOQUEADO")
        self.assertIn("FIXTURE_SINTETICA_NAO_AUTORIZADA",x["bloqueios"])
        ok=avaliar_elegibilidade(pacote(),corte=CORTE,permitir_sintetico=True)
        self.assertEqual(ok["estado"],"ELEGIVEL_EXPERIMENTO_SINTETICO")
        self.assertFalse(ok["homologacao_externa_verificada"])
        self.assertEqual(ok["competencias_asof"],6)
        self.assertEqual(len(ok["hash_pacote"]),64)

    def test_serie_sintetica_pode_ser_recuperada_sem_treino_automatico(self):
        out=serie_elegivel_experimental(pacote(),corte=CORTE,
                                        permitir_sintetico=True)
        self.assertEqual(len(out),6)
        self.assertTrue(all(o.natureza=="OBSERVADO" for o in out))

    def test_real_desativado_no_catalogo_nao_pode_ser_usado(self):
        real=pacote(modo="REAL_AUTORIZADO")
        catalogo={"datasets":[{"id":"CONAB_SAFRAS","source_id":"CONAB",
               "enabled":False,"collection_authorized":False,
               "training_authorized":False}]}
        x=avaliar_elegibilidade(real,corte=CORTE,catalogo=catalogo)
        self.assertEqual(x["estado"],"BLOQUEADO")
        self.assertIn("CATALOGO_REAL_SEM_AUTORIZACAO_DE_TREINO",x["bloqueios"])
        with self.assertRaises(PermissionError):
            serie_elegivel_experimental(real,corte=CORTE,catalogo=catalogo)

    def test_real_com_autorizacao_declarada_nao_vira_sintetico_ou_producao(self):
        real=pacote(modo="REAL_AUTORIZADO")
        catalogo={"datasets":[{"id":"CONAB_SAFRAS","source_id":"CONAB",
                "enabled":True,"collection_authorized":True,
                "training_authorized":True}]}
        x=avaliar_elegibilidade(real,corte=CORTE,catalogo=catalogo)
        self.assertEqual(x["estado"],"CANDIDATO_REAL_COM_APROVACOES_DECLARADAS")
        self.assertFalse(x["homologacao_externa_verificada"])
        with self.assertRaises(PermissionError):
            serie_elegivel_experimental(real,corte=CORTE,catalogo=catalogo)

    def test_permissa_de_treinar_nao_deriva_de_armazenar(self):
        at=certificado(1,operacoes=frozenset(("ARMAZENAMENTO","ANALISE")))
        x=avaliar_elegibilidade([at],corte=CORTE,permitir_sintetico=True,minimo_periodos=1)
        self.assertIn("DIREITOS_DE_TREINAMENTO_NAO_COMPROVADOS",x["bloqueios"])

    def test_estimativa_ou_projecao_nunca_vira_resultado_real(self):
        for natureza,classe in (("INFORMADO","INFORMADO"),
                                ("ESTIMADO","ESTIMADO"),
                                ("PROJETADO","PROJETADO")):
            with self.subTest(natureza=natureza):
                x=avaliar_elegibilidade(
                    [certificado(1,natureza=natureza,classe=classe)],
                    corte=CORTE,permitir_sintetico=True,minimo_periodos=1)
                self.assertEqual(x["estado"],"BLOQUEADO")
                self.assertIn("NATUREZA_OU_CLASSE_NAO_OBSERVADA",x["bloqueios"])

    def test_natureza_observada_com_classe_de_estimativa_e_bloqueada(self):
        x=avaliar_elegibilidade(
            [certificado(1,classe="INFORMADO")],corte=CORTE,
            permitir_sintetico=True,minimo_periodos=1)
        self.assertEqual(x["estado"],"BLOQUEADO")

    def test_mesma_observacao_alterada_após_parecer_rejeita(self):
        at=certificado(1)
        adulterado=replace(at,observacao=replace(at.observacao,valor=999.))
        with self.assertRaises(ErroElegibilidade):
            avaliar_elegibilidade([adulterado],corte=CORTE,permitir_sintetico=True)

    def test_edicao_com_sha_divergente_rejeita(self):
        at=certificado(1)
        with self.assertRaises(ErroElegibilidade):
            avaliar_elegibilidade([replace(at,arquivo_sha256="a"*64)],
                                  corte=CORTE,permitir_sintetico=True)

    def test_parecer_nao_pode_ter_revisores_iguais_ou_autor_modelo(self):
        for reviewers in (("REVISOR_UM","REVISOR_UM"),("PESQUISADOR","REVISOR_DOIS")):
            with self.subTest(reviewers=reviewers):
                with self.assertRaises(ErroElegibilidade):
                    avaliar_elegibilidade(
                        [replace(certificado(1),revisores=reviewers)],
                        corte=CORTE,permitir_sintetico=True)

    def test_aprovacao_anterior_a_coleta_ou_futura_rejeita(self):
        for aprovado in (datetime(2025,1,1,tzinfo=UTC),
                         datetime(2027,1,1,tzinfo=UTC)):
            with self.subTest(aprovado=aprovado):
                with self.assertRaises(ErroElegibilidade):
                    avaliar_elegibilidade(
                        [replace(certificado(1),aprovado_em=aprovado)],
                        corte=CORTE,permitir_sintetico=True)

    def test_duplicacao_versao_rejeitada(self):
        a=certificado(1)
        with self.assertRaises(ErroElegibilidade):
            avaliar_elegibilidade([a,a],corte=CORTE,permitir_sintetico=True)

    def test_revisao_posterior_substitui_label_somente_apos_corte(self):
        old=certificado(1)
        nova=certificado(1,valor=120.,revisao=True,
                        aprovado_em=datetime(2026,2,2,tzinfo=UTC))
        x=avaliar_elegibilidade([old,nova],corte=CORTE,
                               permitir_sintetico=True,minimo_periodos=1)
        self.assertEqual(x["competencias_asof"],1)
        serie=serie_elegivel_experimental([old,nova],corte=CORTE,
                                        permitir_sintetico=True,minimo_periodos=1)
        self.assertEqual(serie[0].valor,120.)

    def test_revisao_futura_nao_fica_elegivel_para_corte_historico(self):
        velha=certificado(1,aprovado_em=datetime(2025,4,1,tzinfo=UTC))
        nova=certificado(1,valor=120.,revisao=True,
                        aprovado_em=datetime(2026,2,2,tzinfo=UTC))
        with self.assertRaises(ErroElegibilidade):
            avaliar_elegibilidade([velha,nova],
                corte=datetime(2025,5,1,tzinfo=UTC),permitir_sintetico=True)

    def test_mistura_de_datasets_reais_e_sinteticos_bloqueia(self):
        x=avaliar_elegibilidade([certificado(1),certificado(2,modo="REAL_AUTORIZADO")],
            corte=CORTE,permitir_sintetico=True,minimo_periodos=2)
        self.assertIn("REAL_E_SINTETICO_MISTURADOS",x["bloqueios"])

    def test_fonte_cultura_ou_unidade_nao_sao_combinadas(self):
        at=certificado(1)
        outra=certificado(2)
        novaobs=replace(outra.observacao,produto="MILHO")
        outra=replace(outra,observacao=novaobs,observacao_sha256=hash_observacao(novaobs))
        with self.assertRaises(ErroElegibilidade):
            avaliar_elegibilidade([at,outra],corte=CORTE,
                                  permitir_sintetico=True)

    def test_catalogo_com_somente_coleta_nao_autoriza_treino(self):
        r=certificado(1,modo="REAL_AUTORIZADO")
        c={"datasets":[{"id":"CONAB_SAFRAS","source_id":"CONAB",
            "enabled":True,"collection_authorized":True}]}
        x=avaliar_elegibilidade([r],corte=CORTE,catalogo=c,minimo_periodos=1)
        self.assertEqual(x["estado"],"BLOQUEADO")

    def test_sem_3_periodos_rejeita_por_amostra_insuficiente(self):
        x=avaliar_elegibilidade([certificado(1)],corte=CORTE,
            permitir_sintetico=True)
        self.assertIn("PERIODOS_INSUFICIENTES",x["bloqueios"])


if __name__=="__main__":
    unittest.main()
