-- NIVON R12: blueprint transacional PostgreSQL para um único banco COMPARTILHADO.
-- NÃO EXECUTADO em instância real; nenhuma migração de registros legados.
-- Este esquema não autentica o titular, WABA nem o gateway externo.
-- Aplicar só após revisão, backup/rollback e autorização explícita.
BEGIN;

CREATE SCHEMA IF NOT EXISTS nivon_mensageria;

CREATE TABLE IF NOT EXISTS nivon_mensageria.consentimentos (
  destinatario_hmac CHAR(64) PRIMARY KEY
    CHECK (destinatario_hmac ~ '^[0-9a-f]{64}$'),
  estado TEXT NOT NULL CHECK (estado IN ('CONCEDIDO','REVOGADO')),
  evidencia_id VARCHAR(160) NOT NULL,
  assinatura_sha256 CHAR(64) NOT NULL
    CHECK (assinatura_sha256 ~ '^[0-9a-f]{64}$'),
  decidido_utc TIMESTAMPTZ NOT NULL,
  atualizado_utc TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION nivon_mensageria.consentimento_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' THEN
    IF NEW.destinatario_hmac IS DISTINCT FROM OLD.destinatario_hmac THEN
      RAISE EXCEPTION 'identidade de consentimento imutável';
    END IF;
    IF OLD.estado='REVOGADO' AND NEW.estado<>'REVOGADO' THEN
      RAISE EXCEPTION 'revogação terminal; reoptin exige processo separado';
    END IF;
    IF NEW.decidido_utc<OLD.decidido_utc THEN
      RAISE EXCEPTION 'decisão temporal retroativa rejeitada';
    END IF;
    IF OLD.estado='CONCEDIDO' AND NEW.estado='CONCEDIDO'
       AND (NEW.evidencia_id IS DISTINCT FROM OLD.evidencia_id
            OR NEW.decidido_utc IS DISTINCT FROM OLD.decidido_utc) THEN
      RAISE EXCEPTION 'renovação sem nova evidência independente';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_consentimento_guard ON nivon_mensageria.consentimentos;
CREATE TRIGGER trg_consentimento_guard BEFORE UPDATE
  ON nivon_mensageria.consentimentos FOR EACH ROW
  EXECUTE FUNCTION nivon_mensageria.consentimento_guard();

CREATE TABLE IF NOT EXISTS nivon_mensageria.reservas (
  dia_local DATE NOT NULL,
  destinatario_hmac CHAR(64) NOT NULL
    REFERENCES nivon_mensageria.consentimentos(destinatario_hmac),
  canal TEXT NOT NULL CHECK (canal IN ('BRIEFING','WHATSAPP')),
  intencao_id VARCHAR(160) NOT NULL,
  estado TEXT NOT NULL CHECK (estado IN ('RESERVADA','BLOQUEADA_REVOGACAO')),
  reservada_utc TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(dia_local,destinatario_hmac),
  UNIQUE(canal,intencao_id)
);
CREATE INDEX IF NOT EXISTS idx_reservas_canal_intencao
  ON nivon_mensageria.reservas(canal,intencao_id);

CREATE OR REPLACE FUNCTION nivon_mensageria.reserva_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE consentimento TEXT;
BEGIN
  IF TG_OP='UPDATE' THEN
    IF (NEW.dia_local,NEW.destinatario_hmac,NEW.canal,NEW.intencao_id)
       IS DISTINCT FROM
       (OLD.dia_local,OLD.destinatario_hmac,OLD.canal,OLD.intencao_id) THEN
      RAISE EXCEPTION 'identidade/edição de reserva imutáveis';
    END IF;
    IF OLD.estado='BLOQUEADA_REVOGACAO' AND NEW.estado<>'BLOQUEADA_REVOGACAO' THEN
      RAISE EXCEPTION 'reserva revogada não pode reativar';
    END IF;
  ELSE
    -- Serializa opt-out e reserva pelo mesmo row lock do consentimento.
    SELECT estado INTO consentimento
      FROM nivon_mensageria.consentimentos
      WHERE destinatario_hmac=NEW.destinatario_hmac FOR UPDATE;
    IF consentimento IS DISTINCT FROM 'CONCEDIDO' THEN
      RAISE EXCEPTION 'opt-in não demonstrado ou revogado';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_reserva_guard ON nivon_mensageria.reservas;
CREATE TRIGGER trg_reserva_guard BEFORE INSERT OR UPDATE
  ON nivon_mensageria.reservas FOR EACH ROW
  EXECUTE FUNCTION nivon_mensageria.reserva_guard();

CREATE OR REPLACE FUNCTION nivon_mensageria.consentimento_revoga_reservas()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.estado='REVOGADO' AND OLD.estado<>'REVOGADO' THEN
    UPDATE nivon_mensageria.reservas
       SET estado='BLOQUEADA_REVOGACAO'
     WHERE destinatario_hmac=NEW.destinatario_hmac
       AND estado='RESERVADA';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_consentimento_revogacao
  ON nivon_mensageria.consentimentos;
CREATE TRIGGER trg_consentimento_revogacao AFTER UPDATE
  ON nivon_mensageria.consentimentos FOR EACH ROW
  EXECUTE FUNCTION nivon_mensageria.consentimento_revoga_reservas();

CREATE TABLE IF NOT EXISTS nivon_mensageria.recibos (
  dia_local DATE NOT NULL,
  destinatario_hmac CHAR(64) NOT NULL,
  canal TEXT NOT NULL CHECK (canal IN ('BRIEFING','WHATSAPP')),
  intencao_id VARCHAR(160) NOT NULL,
  provider_message_id VARCHAR(256) NOT NULL UNIQUE,
  estado TEXT NOT NULL CHECK
    (estado IN ('ACEITO_PROVEDOR','ENVIADO','ENTREGUE','LIDO','FALHOU')),
  aceite_utc TIMESTAMPTZ NOT NULL,
  atualizado_utc TIMESTAMPTZ NOT NULL,
  entregue_utc TIMESTAMPTZ,
  PRIMARY KEY(dia_local,destinatario_hmac),
  FOREIGN KEY(dia_local,destinatario_hmac)
    REFERENCES nivon_mensageria.reservas(dia_local,destinatario_hmac)
);

CREATE OR REPLACE FUNCTION nivon_mensageria.recibo_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE rank_old INT;
DECLARE rank_new INT;
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.estado<>'ACEITO_PROVEDOR' OR NEW.entregue_utc IS NOT NULL THEN
      RAISE EXCEPTION 'primeiro ACK não é entrega';
    END IF;
    IF NOT EXISTS(
      SELECT 1 FROM nivon_mensageria.reservas r
       WHERE r.dia_local=NEW.dia_local
         AND r.destinatario_hmac=NEW.destinatario_hmac
         AND r.canal=NEW.canal AND r.intencao_id=NEW.intencao_id
    ) THEN
      RAISE EXCEPTION 'ACK de intenção sem reserva coincidente';
    END IF;
  ELSE
    IF (NEW.dia_local,NEW.destinatario_hmac,NEW.canal,NEW.intencao_id,
        NEW.provider_message_id,NEW.aceite_utc) IS DISTINCT FROM
       (OLD.dia_local,OLD.destinatario_hmac,OLD.canal,OLD.intencao_id,
        OLD.provider_message_id,OLD.aceite_utc) THEN
      RAISE EXCEPTION 'vínculo com provedor é imutável';
    END IF;
    rank_old:=CASE OLD.estado WHEN 'ACEITO_PROVEDOR' THEN 0 WHEN 'ENVIADO' THEN 1
      WHEN 'ENTREGUE' THEN 2 WHEN 'LIDO' THEN 3 ELSE -1 END;
    rank_new:=CASE NEW.estado WHEN 'ACEITO_PROVEDOR' THEN 0 WHEN 'ENVIADO' THEN 1
      WHEN 'ENTREGUE' THEN 2 WHEN 'LIDO' THEN 3 ELSE -1 END;
    IF OLD.estado='FALHOU' AND NEW.estado<>'FALHOU'
      OR (OLD.estado IN ('ENTREGUE','LIDO') AND NEW.estado='FALHOU')
      OR (NEW.estado<>'FALHOU' AND rank_new<rank_old) THEN
      RAISE EXCEPTION 'estado do recibo não pode regredir';
    END IF;
    IF OLD.entregue_utc IS NOT NULL
       AND NEW.entregue_utc IS DISTINCT FROM OLD.entregue_utc THEN
      RAISE EXCEPTION 'timestamp de entrega original é imutável';
    END IF;
    IF NEW.estado NOT IN ('ENTREGUE','LIDO')
       AND NEW.entregue_utc IS NOT NULL THEN
      RAISE EXCEPTION 'somente entrega/leitura admite instante de entrega';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_recibo_guard ON nivon_mensageria.recibos;
CREATE TRIGGER trg_recibo_guard BEFORE INSERT OR UPDATE
  ON nivon_mensageria.recibos FOR EACH ROW
  EXECUTE FUNCTION nivon_mensageria.recibo_guard();

CREATE TABLE IF NOT EXISTS nivon_mensageria.post_tentativas (
  dia_local DATE NOT NULL,
  destinatario_hmac CHAR(64) NOT NULL,
  intencao_id VARCHAR(160) NOT NULL,
  consumida_utc TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(dia_local,destinatario_hmac),
  UNIQUE(intencao_id),
  FOREIGN KEY(dia_local,destinatario_hmac)
    REFERENCES nivon_mensageria.reservas(dia_local,destinatario_hmac)
);

CREATE OR REPLACE FUNCTION nivon_mensageria.post_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE permitido BOOLEAN;
BEGIN
  -- Serializa contra revogação no consentimento; ainda não cobre trânsito POST.
  SELECT (c.estado='CONCEDIDO' AND r.estado='RESERVADA'
          AND r.intencao_id=NEW.intencao_id)
    INTO permitido
    FROM nivon_mensageria.reservas r
    JOIN nivon_mensageria.consentimentos c
      ON c.destinatario_hmac=r.destinatario_hmac
   WHERE r.dia_local=NEW.dia_local AND r.destinatario_hmac=NEW.destinatario_hmac
   FOR UPDATE OF c,r;
  IF permitido IS DISTINCT FROM TRUE THEN
    RAISE EXCEPTION 'sem opt-in/reserva; POST negado';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_post_guard ON nivon_mensageria.post_tentativas;
CREATE TRIGGER trg_post_guard BEFORE INSERT
  ON nivon_mensageria.post_tentativas FOR EACH ROW
  EXECUTE FUNCTION nivon_mensageria.post_guard();

CREATE TABLE IF NOT EXISTS nivon_mensageria.quarentena_legacy (
  registro_sha256 CHAR(64) PRIMARY KEY CHECK (registro_sha256 ~ '^[0-9a-f]{64}$'),
  fingerprint_sha256 CHAR(64) NOT NULL CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
  motivo VARCHAR(100) NOT NULL,
  criado_utc TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  estado TEXT NOT NULL DEFAULT 'PENDENTE' CHECK (estado='PENDENTE')
);
COMMENT ON SCHEMA nivon_mensageria IS
  'NIVON: schema de contrato offline, SEM atestação de opt-in, tenant ou custo.';
COMMIT;
