-- Esquema de la v3, versión 4: una RESERVA de códigos de caja en lugar de uno solo (pedido el
-- 2026-11-24). Quien tiene "abrir_caja_sin_limite" agrega varios; la empleada escribe cualquiera de
-- los disponibles y ese se gasta (un solo uso, como antes). Se guardan como hash con sal, nunca en
-- texto. Uno disponible se puede retirar (si se filtró): queda marcado, no se borra (historial).
CREATE TABLE codigos_caja (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    hash               TEXT NOT NULL,
    sal                TEXT NOT NULL,
    creado_en          TEXT NOT NULL,
    creado_sesion_id   INTEGER REFERENCES sesiones_sistema(id),
    usado_en           TEXT,
    usado_sesion_id    INTEGER REFERENCES sesiones_sistema(id),
    retirado_en        TEXT,
    retirado_sesion_id INTEGER REFERENCES sesiones_sistema(id)
);
CREATE INDEX codigos_caja_disponibles ON codigos_caja (id) WHERE usado_en IS NULL AND retirado_en IS NULL;

-- El código de la versión 2 (uno solo) pasa a la reserva, con su estado.
INSERT INTO codigos_caja (hash, sal, creado_en, creado_sesion_id, usado_en, usado_sesion_id)
    SELECT hash, sal, creado_en, creado_sesion_id, usado_en, usado_sesion_id FROM codigo_caja;
DROP TABLE codigo_caja;
