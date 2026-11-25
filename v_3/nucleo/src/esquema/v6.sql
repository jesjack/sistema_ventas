-- Esquema de la v3, versión 6: la empleada verifica el corte con el que empieza su día (pedido el
-- 2026-11-24). Nancy hace el corte (al cerrar o en la mañana) y la empleada, al abrir, cuenta el
-- cambio de la caja y dice si cuadra. Queda aquí y como evento en VENTAS REALIZADAS, para que
-- quien hizo el corte lo vea aunque no esté presente.
CREATE TABLE verificaciones_corte (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    corte_id   INTEGER NOT NULL REFERENCES cortes_caja(id),
    fecha      TEXT NOT NULL,
    hora       TEXT NOT NULL,
    sesion_id  INTEGER REFERENCES sesiones_sistema(id),
    esperado   REAL NOT NULL,
    contado    REAL NOT NULL,
    evento_id  INTEGER REFERENCES eventos_especiales(id)
);
CREATE INDEX verificaciones_corte_corte ON verificaciones_corte (corte_id);
