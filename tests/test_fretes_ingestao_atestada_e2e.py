"""E2E com fixtures: raw atestado -> WA adapter -> ledger ofertas -> R01.

Sem ligação real ao WhatsApp, chaves de produção, permissionamento real ou
data independente. Todos os provedores/tenants são sintéticos.
"""
import unittest
import sqlite3
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256

from nivon.fretes_ingestao_atestada import (
    ErroIngestaoFrete, ingerir_lote_whatsapp_atestado,
)
from nivon.fretes_ofertas_store import (
    GENESIS, inicializar_store_ofertas_frete,
    verificar_store_ofertas_frete,
)
from nivon.fretes_integracao_r01 import tendencia_ofertas_pareadas
from test_fretes_whatsapp_r01_e2e import (
    PSEUDO, KEYS, EMISSORES, evento_sintetico, assinar,
)


def pacote(dia, i, preco, *, raw_override=None):
    ev,res,rights,col=evento_sintetico(dia,i,preco)
    raw=(f"Anuncio de frete sintético {dia} ponto {i} {preco}".encode()
         if raw_override is None else raw_override)
    fields={k:v for k,v in res.items()
            if k not in {"versao_atestacao","emissor_id","emitido_em",
                         "valido_ate","assinatura_hmac_sha256"}}
    fields["raw_sha256"]=sha256(raw).hexdigest()
    res=assinar(fields,"RESOLUCAO",col)
    return {
        "evento":ev,"resolucao":res,"autorizacao":rights,
        "data_coleta":col,"raw_bytes":raw,
    }


def inserir(db,envs,head=GENESIS,rec=None):
    instante=(envs[0]["data_coleta"]+timedelta(minutes=1)
             if rec is None else rec)
    return ingerir_lote_whatsapp_atestado(
        db,envs,cabeca_anterior_sha256=head,recebido_em=instante,
        chave_pseudonimizacao=PSEUDO,chaves_atestacao=KEYS,
        emissores_atestacao=EMISSORES,
    )


class TestIngestaoAtestadaE2E(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        inicializar_store_ofertas_frete(self.db)
        self.dia=date(2026,10,12)

    def test_lote_2_ofertas_retorna_hash_e_evidencia_sem_raw(self):
        envs=[pacote(self.dia,i,150+i) for i in (1,2)]
        r=inserir(self.db,envs)
        self.assertEqual(r["registros_individuais_inseridos"],2)
        self.assertEqual(r["publicacoes_recebidas"],2)
        self.assertTrue(r["integridade_raw_sha256_vinculada"])
        s=verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=r["cabeca_sha256"])
        self.assertEqual(s["registros"],2)
        self.assertEqual(len(s["evidencias_declaradas"]),2)
        self.assertNotIn("Anuncio de frete sintético",str(s))
        self.assertFalse(s["raw_autenticado_externamente"])
        self.assertFalse(r["publicavel"])
        self.assertFalse(r["origem_externa_autenticada_operacionalmente"])
        self.assertNotIn("tenant-fixture",str(s))

    def test_repetir_mesmos_bytes_e_assinaturas_e_idempotente(self):
        envs=[pacote(self.dia,1,151),pacote(self.dia,2,152)]
        primeiro=inserir(self.db,envs)
        r=inserir(self.db,envs,head=primeiro["cabeca_sha256"])
        self.assertEqual(r["status"],"INGESTAO_IDEMPOTENTE_SEM_NOVOS_REGISTROS")
        self.assertEqual(r["registros_individuais_inseridos"],0)
        self.assertEqual(r["republicacoes_idempotentes"],2)
        self.assertEqual(r["cabeca_sha256"],primeiro["cabeca_sha256"])

    def test_duplica_mesmo_evento_no_lote_so_insere_uma_vez(self):
        e=pacote(self.dia,1,151)
        r=inserir(self.db,[e,e])
        self.assertEqual(r["publicacoes_recebidas"],2)
        self.assertEqual(r["registros_individuais_inseridos"],1)
        self.assertEqual(r["republicacoes_idempotentes"],1)

    def test_raw_modificado_sem_reassinatura_recusa_lote_todo(self):
        envs=[pacote(self.dia,1,151),pacote(self.dia,2,152)]
        envs[1]["raw_bytes"]=b"raw modificado depois do resolvedor"
        with self.assertRaisesRegex(ErroIngestaoFrete,"RAW diferente"):
            inserir(self.db,envs)
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=GENESIS)["registros"],0)

    def test_raw_hash_adulterado_na_resolucao_sem_hmac_valido(self):
        e=pacote(self.dia,1,151)
        e["resolucao"]["raw_sha256"]=sha256(b"inventado").hexdigest()
        e["raw_bytes"]=b"inventado"
        with self.assertRaisesRegex(ErroIngestaoFrete,"validação externa"):
            inserir(self.db,[e])
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=GENESIS)["registros"],0)

    def test_envelope_incompleto_ou_raw_grande_bloqueia(self):
        e=pacote(self.dia,1,151)
        q=dict(e);q.pop("raw_bytes")
        with self.assertRaises(ErroIngestaoFrete):
            inserir(self.db,[q])
        q=dict(e);q["raw_bytes"]=b"x"*200001
        with self.assertRaises(ErroIngestaoFrete):
            inserir(self.db,[q])

    def test_automatico_nao_ingere_replay_tardio(self):
        envs=[pacote(self.dia,1,151)]
        with self.assertRaisesRegex(ErroIngestaoFrete,"retroativo"):
            inserir(self.db,envs,rec=envs[0]["data_coleta"]+timedelta(days=1))
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=GENESIS)["registros"],0)

    def test_cabeca_anterior_nao_confiavel_recusa(self):
        a=inserir(self.db,[pacote(self.dia,1,151)])
        with self.assertRaisesRegex(ErroIngestaoFrete,"cabeça"):
            inserir(self.db,[pacote(self.dia,2,152)],head=GENESIS)
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=a["cabeca_sha256"])["registros"],1)

    def test_whatsapp_para_store_e_tendencia_seis_sessoes(self):
        head=GENESIS
        for j in range(6):
            dia=self.dia+timedelta(days=j)
            envs=[pacote(dia,i,150+i*10+j*3) for i in (1,2)]
            r=inserir(self.db,envs,head=head)
            head=r["cabeca_sha256"]
        s=verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=head)
        self.assertEqual(s["registros"],12)
        resultado=tendencia_ofertas_pareadas(
            s["ofertas"],origem_ibge="5107925",destino_ibge="5107602",
            descarga_entity_id="terminal:001",produto="SOJA",
            equipamento="RODOTREM",regime="PJ",pedagio="ADICIONAL",
            as_of=datetime(2026,10,20,10,tzinfo=timezone.utc),
            janela=6,minimo_pares=2,tolerancia_absoluta=2,
        )
        self.assertEqual(resultado["tendencia"],"ALTA")
        self.assertEqual(len(resultado["identidades_comparaveis"]),2)
        self.assertFalse(resultado["publicavel"])
        self.assertNotIn("frete_medio_municipio",str(resultado))

    def test_uma_assinatura_falsa_recusa_todo_lote(self):
        envs=[pacote(self.dia,1,151),pacote(self.dia,2,152)]
        envs[1]["autorizacao"]["operacoes_permitidas"]=["LEITURA"]
        with self.assertRaises(ErroIngestaoFrete):
            inserir(self.db,envs)
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=GENESIS)["registros"],0)


if __name__=="__main__":
    unittest.main()
