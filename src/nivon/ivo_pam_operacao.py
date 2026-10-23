"""Execução integrada PAM/IBGE: coleta pontual, preservação e SQLite incremental.

Fonte pública de consulta não comercial. Não altera o catálogo principal nem
declara que a data de captura seja publicação oficial. Usa normalizador,
semântica e quarentena existentes. A execução em lote continua após falhas
por item e pode ser repetida sem duplicar observações.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .ivo_pam_coletor_pontual import _fetch_once, _url
from .ivo_pam_quarentena import arquivar_candidato_pam, conferir_recibo_pam
from .ivo_pam_semantica import conferir_semantica_pam_1612
from .sidra_pam import normalizar_pam_1612, planejar_pam_1612
from .transacoes_sqlite import savepoint_atomico


class ErroOperacaoPAM(ValueError):
    pass


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ErroOperacaoPAM("instante timezone-aware necessário")
    return value.astimezone(timezone.utc).isoformat()


def abrir_operacao_pam(caminho=":memory:"):
    """Schema somente de staging, sem alterações no ledger compartilhado."""
    db=sqlite3.connect(str(caminho),timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""CREATE TABLE IF NOT EXISTS pam_vintages(
        municipio TEXT NOT NULL, ano INTEGER NOT NULL, variavel TEXT NOT NULL,
        produto TEXT NOT NULL, sha256 TEXT NOT NULL,
        estado_valor TEXT NOT NULL, valor REAL, unidade TEXT NOT NULL,
        recibo_sha256 TEXT NOT NULL, origem_url TEXT NOT NULL,
        natureza TEXT NOT NULL DEFAULT 'INFORMADO_PAM_ANUAL',
        PRIMARY KEY(municipio,ano,variavel,produto,sha256))""")
    db.execute("""CREATE TABLE IF NOT EXISTS pam_capturas(
        municipio TEXT NOT NULL, ano INTEGER NOT NULL, variavel TEXT NOT NULL,
        produto TEXT NOT NULL, sha256 TEXT NOT NULL, coletado_em TEXT NOT NULL,
        origem TEXT NOT NULL, mudanca TEXT NOT NULL,
        PRIMARY KEY(municipio,ano,variavel,produto,sha256,coletado_em),
        FOREIGN KEY(municipio,ano,variavel,produto,sha256)
          REFERENCES pam_vintages(municipio,ano,variavel,produto,sha256))""")
    db.execute("""CREATE INDEX IF NOT EXISTS idx_pam_capturas_alvo
        ON pam_capturas(municipio,ano,variavel,produto,coletado_em DESC)""")
    db.commit()
    return db


def _plano(item):
    if not isinstance(item,dict):
        raise ErroOperacaoPAM("tarefa PAM inválida")
    plano=planejar_pam_1612(municipio_ibge=item.get("municipio_ibge"),
        ano=item.get("ano"),codigo_produto_c81=item.get("categoria_c81"),
        codigo_variavel=item.get("variavel"))
    unidade="Toneladas" if plano["variavel"]=="214" else "Hectares"
    conferir_semantica_pam_1612(variavel=plano["variavel"],
        categoria_c81=plano["categoria_c81"],unidade=unidade)
    return plano,unidade


def processar_captura_pam(*, db, raiz, plano, payload, coletado_em,
                          origem="ARQUIVO_LOCAL", limite_cofre=64*1024*1024):
    """Uma edição completa: validação -> armazenamento SHA -> vintage -> captura."""
    if not isinstance(db,sqlite3.Connection):
        raise ErroOperacaoPAM("SQLite operacional obrigatório")
    if origem not in ("ARQUIVO_LOCAL","HTTP_PUBLICO","TRANSPORTE_TESTE"):
        raise ErroOperacaoPAM("origem de captura desconhecida")
    data=_utc(coletado_em)
    if not isinstance(payload,bytes) or not 0<len(payload)<=2_000_000:
        raise ErroOperacaoPAM("payload fora do limite")
    esperado,unidade=_plano(plano)
    if esperado!=plano:
        raise ErroOperacaoPAM("plano do coletor adulterado")
    norm=normalizar_pam_1612(payload,plano=plano,coletado_em=data)
    if len(norm["observacoes"])!=1:
        raise ErroOperacaoPAM("apenas uma célula por consulta SIDRA")
    item=norm["observacoes"][0]
    if item["unidade_original"]!=unidade:
        raise ErroOperacaoPAM("unidade PAM incompatível com grandeza")
    digest=hashlib.sha256(payload).hexdigest()
    candidato={
        "estado":"CAPTURA_PONTUAL_PAM_QUARENTENA_NAO_HOMOLOGADA",
        "fonte":"IBGE","dataset_id":"IBGE_PAM","tipo":"SIDRA_JSON",
        "url_exata":plano["url"],"coletado_em":data,
        "sha256":digest,"bytes":len(payload),"conteudo_original":payload,
        "autenticidade_documental_verificada":False,
        "publicacao_oficial_verificada":False,
        "treinamento_autorizado":False,"gravado_em_snapshot_ledger":False,
        # Proveniência da finalidade, NÃO uma certificação de licença.
        "evidencia_direitos_declarada":"IBGE_DADOS_PUBLICOS_ESTUDO_INTERNO",
    }
    armazenado=arquivar_candidato_pam(raiz=raiz,candidato=candidato,
                                     limite_total_bytes=limite_cofre)
    chave=(plano["municipio_ibge"],plano["ano"],plano["variavel"],plano["categoria_c81"])
    anterior=db.execute("""SELECT v.sha256,v.estado_valor,v.valor,c.coletado_em
        FROM pam_vintages v JOIN pam_capturas c
        ON (v.municipio,v.ano,v.variavel,v.produto,v.sha256)=
           (c.municipio,c.ano,c.variavel,c.produto,c.sha256)
        WHERE v.municipio=? AND v.ano=? AND v.variavel=? AND v.produto=?
        ORDER BY c.coletado_em DESC,c.sha256 DESC LIMIT 1""",chave).fetchone()
    if anterior is None:
        mudou="PRIMEIRA_CAPTURA"
    elif anterior["sha256"]==digest:
        mudou="SEM_ALTERACAO"
    elif anterior["estado_valor"]!=item["estado_valor"]:
        mudou="ESTADO_ALTERADO"
    elif item["estado_valor"]=="OBSERVADO_NUMERICO" and anterior["valor"]!=item["valor"]:
        mudou="VALOR_ALTERADO"
    else:
        mudou="NOVOS_BYTES_MESMO_VALOR"
    with savepoint_atomico(db):
        db.execute("""INSERT OR IGNORE INTO pam_vintages
          (municipio,ano,variavel,produto,sha256,estado_valor,valor,unidade,recibo_sha256,origem_url)
          VALUES (?,?,?,?,?,?,?,?,?,?)""",
          (*chave,digest,item["estado_valor"],item["valor"],unidade,
           armazenado["recibo_sha256"],plano["url"]))
        db.execute("""INSERT OR IGNORE INTO pam_capturas
          (municipio,ano,variavel,produto,sha256,coletado_em,origem,mudanca)
          VALUES (?,?,?,?,?,?,?,?)""",(*chave,digest,data,origem,mudou))
    return {
        "estado":"PAM_OPERACIONAL_ARMAZENADO_NAO_HOMOLOGADO",
        "municipio_ibge":chave[0],"ano_civil":chave[1],
        "variavel":chave[2],"categoria_c81":chave[3],"unidade":unidade,
        "sha256":digest,"recibo_sha256":armazenado["recibo_sha256"],
        "coletado_em":data,"alteracao":mudou,
        "valor_candidato":item["valor"] if item["estado_valor"]=="OBSERVADO_NUMERICO" else None,
        "estado_valor":item["estado_valor"],"origem":origem,
        "publicacao_oficial_conhecida":False,"treinamento_habilitado":False,
        "ledger_canonico_modificado":False,
    }


def consultar_pam_operacional(db,*,municipio_ibge,ano,variavel,produto,
                             corte_coleta=None):
    """Consulta histórico inteiro por identidade; sem médias ou projeções."""
    chave,_=_plano({"municipio_ibge":municipio_ibge,"ano":ano,
                    "variavel":variavel,"categoria_c81":produto})
    corte=_utc(corte_coleta) if corte_coleta is not None else None
    rows=db.execute("""SELECT v.sha256,v.estado_valor,v.valor,v.unidade,
       v.recibo_sha256,c.coletado_em,c.mudanca,c.origem
       FROM pam_vintages v JOIN pam_capturas c
       ON (v.municipio,v.ano,v.variavel,v.produto,v.sha256)=
          (c.municipio,c.ano,c.variavel,c.produto,c.sha256)
       WHERE v.municipio=? AND v.ano=? AND v.variavel=? AND v.produto=?
         AND (? IS NULL OR c.coletado_em<=?)
       ORDER BY c.coletado_em,c.sha256 LIMIT 1001""",
       (chave["municipio_ibge"],chave["ano"],chave["variavel"],
        chave["categoria_c81"],corte,corte)).fetchall()
    if len(rows)>1000:
        raise ErroOperacaoPAM("histórico excessivo: consultar períodos separados")
    hist=[dict(r) for r in rows]
    return {"dataset_id":"IBGE_PAM","municipio_ibge":municipio_ibge,
            "ano_civil":ano,"variavel":variavel,"categoria_c81":produto,
            "capturas":len(hist),"ultima":hist[-1] if hist else None,
            "historico":hist,"corte_coleta":corte,
            "natureza":"ESTATISTICA_PAM_ANUAL_INFORMADA",
            "publicacao_reconstituida":False,
            "treinamento_real_habilitado":False}


def _arquivo_local(root,filename):
    if not isinstance(filename,str) or not filename or len(filename)>180:
        raise ErroOperacaoPAM("nome de arquivo local inválido")
    base=Path(root).resolve(strict=True)
    if not base.is_dir():
        raise ErroOperacaoPAM("diretório de entrada inválido")
    filename_path=Path(filename)
    if filename_path.is_absolute() or ".." in filename_path.parts:
        raise ErroOperacaoPAM("caminho local fora da entrada")
    file=base/filename
    if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(base):
        raise ErroOperacaoPAM("arquivo fora do diretório permitido")
    if not 0<file.stat().st_size<=2_000_000:
        raise ErroOperacaoPAM("arquivo SIDRA ausente ou muito grande")
    return file.read_bytes()


def executar_lote_pam(*, db,raiz,tarefas,modo="LOCAL",entrada=None,
                      transporte=None,max_tarefas=30)->dict:
    """Executa até 30 consultas independentes; erro individual não cancela lote.

    LOCAL usa arquivos concretos; PUBLICO_IBGE faz um GET HTTPS por tarefa.
    Transporte injetado é somente para E2E, explicitamente identificado.
    """
    if modo not in ("LOCAL","PUBLICO_IBGE"):
        raise ErroOperacaoPAM("modo desconhecido")
    if not isinstance(tarefas,list) or not 1<=len(tarefas)<=max_tarefas<=30:
        raise ErroOperacaoPAM("lote inválido ou fora do limite de 30 tarefas")
    if modo=="LOCAL" and entrada is None:
        raise ErroOperacaoPAM("diretório de arquivos obrigatório")
    if modo=="LOCAL" and transporte is not None:
        raise ErroOperacaoPAM("transporte não pode ser usado em modo local")
    if transporte is not None and not callable(transporte):
        raise ErroOperacaoPAM("transporte inválido")
    results=[]
    for n,tarefa in enumerate(tarefas):
        try:
            plano,_=_plano(tarefa)
            if modo=="LOCAL":
                payload=_arquivo_local(entrada,tarefa.get("arquivo"))
                origem="ARQUIVO_LOCAL"
            else:
                _url(plano["url"],tipo="SIDRA_JSON")
                out=(transporte or _fetch_once)(plano["url"],2_000_000,12)
                if not isinstance(out,tuple) or len(out)!=2:
                    raise ErroOperacaoPAM("transporte retornou resposta inválida")
                payload,ctype=out
                if not isinstance(ctype,str) or ctype.split(";",1)[0].lower() not in (
                        "application/json","text/json","text/plain","application/octet-stream"):
                    raise ErroOperacaoPAM("resposta não é JSON SIDRA")
                origem="TRANSPORTE_TESTE" if transporte is not None else "HTTP_PUBLICO"
            recebido=datetime.now(timezone.utc)
            row=processar_captura_pam(db=db,raiz=raiz,plano=plano,payload=payload,
                                    coletado_em=recebido,origem=origem)
            results.append({"ordem":n,"status":"OK","resultado":row})
        except (OSError,ValueError,PermissionError,sqlite3.Error,TypeError,KeyError) as exc:
            results.append({"ordem":n,"status":"ERRO","tipo":type(exc).__name__,
                            "motivo":str(exc)[:240]})
    return {"estado":"LOTE_PAM_CONCLUIDO","modo":modo,
            "total":len(results),
            "aprovados":sum(x["status"]=="OK" for x in results),
            "falhas":sum(x["status"]=="ERRO" for x in results),
            "resultados":results,"treinamento_habilitado":False}


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON PAM: coleta e atualização incremental")
    p.add_argument("--modo",choices=("LOCAL","PUBLICO_IBGE"),required=True)
    p.add_argument("--tarefas",type=Path,required=True,
                   help="JSON array de até 30 consultas pontuais")
    p.add_argument("--entrada",type=Path,help="raiz dos arquivos JSON em modo LOCAL")
    p.add_argument("--db",type=Path,required=True,help="SQLite operacional")
    p.add_argument("--acervo",type=Path,required=True,help="quarentena content-addressed")
    args=p.parse_args(argv)
    try:
        tarefas=json.loads(args.tarefas.read_text(encoding="utf-8"))
        args.db.parent.mkdir(parents=True,exist_ok=True)
        db=abrir_operacao_pam(args.db)
        try:
            resultado=executar_lote_pam(db=db,raiz=args.acervo,tarefas=tarefas,
                                       modo=args.modo,entrada=args.entrada)
        finally:
            db.close()
        print(json.dumps(resultado,ensure_ascii=False,indent=2))
        return 0 if resultado["falhas"]==0 else 1
    except (OSError,ValueError,sqlite3.Error) as exc:
        print(json.dumps({"estado":"ERRO","motivo":str(exc)[:250]},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
