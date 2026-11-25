-- Esquema de la v3, versión 5: el corte de caja abre el cajón (como la v2) y esa apertura también
-- entra al registro, con su propia autorización: "corte". SQLite no cambia un CHECK en su sitio:
-- se rehace la tabla con los mismos datos.
CREATE TABLE aperturas_caja_v5 (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha        TEXT NOT NULL,
    hora         TEXT NOT NULL,
    sesion_id    INTEGER REFERENCES sesiones_sistema(id),
    autorizacion TEXT NOT NULL CHECK (autorizacion IN ('permiso', 'ventana_diaria', 'codigo', 'venta', 'corte')),
    venta_id     INTEGER REFERENCES ventas(id),
    evento_id    INTEGER REFERENCES eventos_especiales(id)
);
INSERT INTO aperturas_caja_v5 (id, fecha, hora, sesion_id, autorizacion, venta_id, evento_id)
    SELECT id, fecha, hora, sesion_id, autorizacion, venta_id, evento_id FROM aperturas_caja;
DROP TABLE aperturas_caja;
ALTER TABLE aperturas_caja_v5 RENAME TO aperturas_caja;
CREATE INDEX aperturas_caja_fecha ON aperturas_caja (fecha);
