"""Backfill PTAX com checkpoints locais, idempotência e retomada após interrupção.

Uso: executar em host com disco privado/durável. GitHub Actions hospedado é efêmero.
O módulo não agenda tarefas, não instala serviços e não envia séries ao GitHub.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time

from nivon.ptax_bcb import (
    DATA_INICIAL_PUBLICA, MOEDAS, PAGINA_DIAS, sincronizar,
)

RAIZ_REPO = Path(__file__).resolve().parents[1]


def banco_privado(caminho: Path | str) -> Path:
    """Bloqueia bancos reais dentro do checkout público, inclusive via symlink."""
    arquivo = Path(caminho).expanduser().resolve()
    if arquivo == RAIZ_REPO or RAIZ_REPO in arquivo.parents:
        raise ValueError("Banco não pode ficar dentro do repositório público")
    if not arquivo.parent.is_dir():
        raise ValueError("Diretório privado do banco deve existir")
    return arquivo


def janelas_backfill(inicio: date, fim: date, dias: int = PAGINA_DIAS):
    if not 1 <= dias <= PAGINA_DIAS:
        raise ValueError("Janela deve ter entre 1 e 31 dias")
    if inicio > fim:
        raise ValueError("Início posterior ao fim")
    atual = inicio
    while atual <= fim:
        termino = min(fim, atual + timedelta(days=dias - 1))
        yield atual, termino
        atual = termino + timedelta(days=1)


def criar_checkpoint(conn: sqlite3.Connection):
    conn.execute("""CREATE TABLE IF NOT EXISTS ptax_backfill_janelas (
        moeda TEXT NOT NULL,
        inicio TEXT NOT NULL,
        fim TEXT NOT NULL,
        estado TEXT NOT NULL,
        tentativas INTEGER NOT NULL DEFAULT 0,
        registros_recebidos INTEGER,
        novos_ou_revisados INTEGER,
        ultima_tentativa_utc TEXT,
        erro TEXT,
        PRIMARY KEY(moeda, inicio, fim)
    )""")


def status_checkpoint(conn: sqlite3.Connection, moeda: str, inicio: date, fim: date):
    linha = conn.execute(
        "SELECT estado FROM ptax_backfill_janelas WHERE moeda=? AND inicio=? AND fim=?",
        (moeda, inicio.isoformat(), fim.isoformat()),
    ).fetchone()
    return linha[0] if linha else None


def marcar_checkpoint(conn: sqlite3.Connection, moeda: str, a: date, b: date,
                      estado: str, recebidos=None, novos=None, erro=None) -> None:
    if estado not in {"SUCESSO", "SEM_COTACAO_NO_PERIODO", "FALHOU"}:
        raise ValueError("Estado desconhecido")
    instante = datetime.now(timezone.utc).isoformat()
    conn.execute("""INSERT INTO ptax_backfill_janelas
        (moeda, inicio, fim, estado, tentativas, registros_recebidos,
         novos_ou_revisados, ultima_tentativa_utc, erro)
        VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
        ON CONFLICT(moeda, inicio, fim) DO UPDATE SET
          estado=excluded.estado,
          tentativas=ptax_backfill_janelas.tentativas+1,
          registros_recebidos=excluded.registros_recebidos,
          novos_ou_revisados=excluded.novos_ou_revisados,
          ultima_tentativa_utc=excluded.ultima_tentativa_utc,
          erro=excluded.erro""",
        (moeda, a.isoformat(), b.isoformat(), estado,
         recebidos, novos, instante, erro))


def recuperar_historico(
    banco: Path | str, moeda: str, inicio: date, fim: date, *,
    dias_janela: int = PAGINA_DIAS,
    max_janelas: int = 8,
    segundos_entre_consultas: float = 0.5,
    revalidar: bool = False,
    dias_revisao: int = 7,
    hoje: date | None = None,
    transporte=None,
    dry_run: bool = False,
) -> dict:
    """Usa transações do coletor por janela, para sobreviver a falhas intermediárias.

    Retorno PARCIAL_LIMITE não significa histórico completo. Janela vazia também
    recebe checkpoint; períodos próximos a hoje são reconsultados.
    """
    moeda = moeda.upper()
    hoje = hoje or date.today()
    if moeda not in MOEDAS or inicio < DATA_INICIAL_PUBLICA[moeda] or inicio > fim or fim > hoje:
        raise ValueError("Moeda ou período fora da cobertura")
    if not 1 <= dias_janela <= PAGINA_DIAS:
        raise ValueError("dias_janela deve ser 1..31")
    if max_janelas < 1 or max_janelas > 64:
        raise ValueError("max_janelas deve ser 1..64")
    if not 0 <= segundos_entre_consultas <= 30:
        raise ValueError("intervalo entre consultas inválido")
    if not 0 <= dias_revisao <= 60:
        raise ValueError("dias_revisao deve ser 0..60")
    banco = banco_privado(banco)
    janelas = list(janelas_backfill(inicio, fim, dias_janela))
    if dry_run:
        return {
            "estado": "PLANEJADO_SEM_COLETA",
            "moeda": moeda, "inicio": inicio.isoformat(), "fim": fim.isoformat(),
            "janelas_totais": len(janelas), "janelas_limite_por_rodada": max_janelas,
            "dias_janela": dias_janela, "arquivo_banco": str(banco),
        }
    result = {
        "estado": "COMPLETO", "moeda": moeda, "inicio": inicio.isoformat(),
        "fim": fim.isoformat(), "janelas_totais": len(janelas),
        "janelas_executadas": 0, "janelas_puladas": 0,
        "registros_recebidos": 0, "novos_ou_revisados": 0,
        "arquivo_banco": str(banco),
    }
    with sqlite3.connect(str(banco), timeout=30) as conn:
        criar_checkpoint(conn)
        conn.commit()
        for a, b in janelas:
            anterior = status_checkpoint(conn, moeda, a, b)
            # Reprocessar também janelas vazias recentes para não perder boletins tardios.
            recente = b >= hoje - timedelta(days=dias_revisao)
            if anterior in ("SUCESSO", "SEM_COTACAO_NO_PERIODO") and not revalidar and not recente:
                result["janelas_puladas"] += 1
                continue
            if result["janelas_executadas"] >= max_janelas:
                result["estado"] = "PARCIAL_LIMITE"
                break
            if result["janelas_executadas"] and segundos_entre_consultas:
                time.sleep(segundos_entre_consultas)
            try:
                # Sincronizar realiza transação atômica por janela (inclui observações
                # e log). Falha aborta essa janela, mantendo anteriores.
                saida = sincronizar(banco, moeda, inicio=a, fim=b,
                                   transporte=transporte, hoje=hoje)
            except Exception as exc:
                # Erro auditável e seguro: não registrar URLs/credenciais.
                marcar_checkpoint(conn, moeda, a, b, "FALHOU", erro=type(exc).__name__)
                conn.commit()
                raise RuntimeError(
                    f"Backfill {moeda} interrompido na janela {a.isoformat()}..{b.isoformat()}; "
                    "checkpoint registrado e janelas anteriores preservadas"
                ) from exc
            marcar_checkpoint(conn, moeda, a, b, saida["estado"],
                              recebidos=saida["recebidos"],
                              novos=saida["novos_ou_revisados"])
            conn.commit()
            result["janelas_executadas"] += 1
            result["registros_recebidos"] += saida["recebidos"]
            result["novos_ou_revisados"] += saida["novos_ou_revisados"]
    # Confirmar cobertura somente quando todas as janelas estão carimbadas como
    # sucesso ou sem cotação; limite por rodada não é sinônimo de falha.
    with sqlite3.connect(str(banco)) as conn:
        criar_checkpoint(conn)
        pendentes = [
            (a, b) for a, b in janelas
            if status_checkpoint(conn, moeda, a, b)
            not in ("SUCESSO", "SEM_COTACAO_NO_PERIODO")
        ]
    result["janelas_pendentes"] = len(pendentes)
    if pendentes:
        result["estado"] = "PARCIAL_LIMITE"
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="NIVON — backfill PTAX reentrante no banco local")
    p.add_argument("--banco", type=Path, required=True)
    p.add_argument("--moeda", choices=("USD", "EUR"), required=True)
    p.add_argument("--inicio", type=date.fromisoformat, required=True)
    p.add_argument("--fim", type=date.fromisoformat, required=True)
    p.add_argument("--dias-janela", type=int, default=PAGINA_DIAS)
    p.add_argument("--max-janelas", type=int, default=8)
    p.add_argument("--intervalo-segundos", type=float, default=0.5)
    p.add_argument("--revalidar", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    print(json.dumps(recuperar_historico(
        args.banco, args.moeda, args.inicio, args.fim,
        dias_janela=args.dias_janela, max_janelas=args.max_janelas,
        segundos_entre_consultas=args.intervalo_segundos,
        revalidar=args.revalidar, dry_run=args.dry_run,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
