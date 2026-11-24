-- Esquema de la v3, versión 2: turno de caja, permisos, código de autorización y registro de
-- aperturas. Decisiones en v_3/docs/mapa_v2.md (D8, D20, D21, D23) y su repaso sin Calc.

-- D8. Turno de caja: una sola caja activa por equipo. Una única fila con el turno vigente. Tomar la
-- caja = `numero = numero + 1` en una transacción; la caja anterior se entera en su siguiente
-- comprobación (cada ~3 s) de que su número ya no es el vigente, no hace nada más y se cierra.
CREATE TABLE turno_caja (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    numero    INTEGER NOT NULL,
    sesion_id INTEGER REFERENCES sesiones_sistema(id),
    desde     TEXT NOT NULL
);
INSERT INTO turno_caja (id, numero, sesion_id, desde) VALUES (1, 0, NULL, '');

-- D21. Permisos por usuario (no por nombre en el código). Los asigna el desarrollador.
--   desarrollador          menú de administración (botones, configuración, permisos)
--   abrir_caja_sin_limite  "Abrir caja" siempre, sin código; configura el código de autorización
--   empleada               "Abrir caja" una vez al día por caja, antes de la primera venta
CREATE TABLE permisos_usuario (
    usuario_id INTEGER NOT NULL REFERENCES usuarios_sistema(id) ON DELETE CASCADE,
    permiso    TEXT NOT NULL CHECK (permiso IN ('desarrollador', 'abrir_caja_sin_limite', 'empleada')),
    PRIMARY KEY (usuario_id, permiso)
);

-- D20/D21. El código de autorización para abrir la caja: uno solo, guardado como hash con sal (nunca
-- en texto plano), y de UN SOLO USO: al usarse queda bloqueado (`usado_en`) hasta que alguien con
-- "abrir_caja_sin_limite" ponga uno nuevo. Sin fila = todavía no hay código.
CREATE TABLE codigo_caja (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    hash             TEXT NOT NULL,
    sal              TEXT NOT NULL,
    creado_en        TEXT NOT NULL,
    creado_sesion_id INTEGER REFERENCES sesiones_sistema(id),
    usado_en         TEXT,
    usado_sesion_id  INTEGER REFERENCES sesiones_sistema(id)
);

-- D21/D23. Cada vez que se abrió el cajón, en un solo lugar: quién (sesión), cuándo y cómo se
-- autorizó. Las aperturas por una venta también ("venta"). Nunca se guarda el código.
CREATE TABLE aperturas_caja (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha        TEXT NOT NULL,
    hora         TEXT NOT NULL,
    sesion_id    INTEGER REFERENCES sesiones_sistema(id),
    autorizacion TEXT NOT NULL CHECK (autorizacion IN ('permiso', 'ventana_diaria', 'codigo', 'venta')),
    venta_id     INTEGER REFERENCES ventas(id),
    evento_id    INTEGER REFERENCES eventos_especiales(id)
);
CREATE INDEX aperturas_caja_fecha ON aperturas_caja (fecha);
