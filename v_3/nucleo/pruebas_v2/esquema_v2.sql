-- Generado por generar_casos.py: el esquema de la v2 recién creado, con sus datos semilla.
CREATE TABLE autorizaciones_codigos (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo    TEXT NOT NULL,
                    evento_id INTEGER REFERENCES eventos_especiales(id)
                );
CREATE TABLE catalogo_autocompletado (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                producto   TEXT NOT NULL UNIQUE COLLATE NOCASE,
                creado_en  TEXT DEFAULT CURRENT_TIMESTAMP
            , sesion_id INTEGER REFERENCES sesiones_sistema(id), actualizado_en TEXT, actualizado_sesion_id INTEGER REFERENCES sesiones_sistema(id));
CREATE TABLE codigos_barras_registrados (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_barras  TEXT NOT NULL UNIQUE COLLATE NOCASE,
                producto_id    INTEGER NOT NULL REFERENCES catalogo_autocompletado(id),
                precio_venta   REAL NOT NULL,
                creado_en      TEXT DEFAULT CURRENT_TIMESTAMP
            , sesion_id INTEGER REFERENCES sesiones_sistema(id), actualizado_en TEXT, actualizado_sesion_id INTEGER REFERENCES sesiones_sistema(id));
CREATE TABLE cortes_caja (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha            TEXT NOT NULL,
                hora             TEXT NOT NULL,
                ultima_venta_id  INTEGER NOT NULL,
                ultimo_evento_id INTEGER NOT NULL,
                sesion_id        INTEGER REFERENCES sesiones_sistema(id)
            );
CREATE TABLE cortes_caja_cambio (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                corte_id     INTEGER NOT NULL REFERENCES cortes_caja(id),
                tipo         TEXT NOT NULL,
                denominacion REAL NOT NULL,
                cantidad     INTEGER NOT NULL
            );
CREATE TABLE eventos_especiales (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha    TEXT NOT NULL,
                hora     TEXT NOT NULL,
                evento   TEXT NOT NULL,
                detalle  TEXT
            , sesion_id INTEGER REFERENCES sesiones_sistema(id));
CREATE TABLE impresiones_codigos_barras (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha         TEXT NOT NULL,
                hora          TEXT NOT NULL,
                codigo_barras TEXT NOT NULL,
                copias        INTEGER NOT NULL,
                horizontal    INTEGER NOT NULL DEFAULT 0,
                codificador   TEXT,
                sesion_id     INTEGER REFERENCES sesiones_sistema(id)
            , piezas INTEGER);
CREATE TABLE sesiones_sistema (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id            INTEGER NOT NULL REFERENCES usuarios_sistema(id),
                inicio                TEXT NOT NULL,
                ultimo_latido         TEXT NOT NULL,
                salida_real           TEXT,
                cerrada_correctamente INTEGER NOT NULL DEFAULT 0,
                pid                   INTEGER,
                detalle               TEXT
            );
CREATE TABLE usuarios_sistema (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_usuario    TEXT NOT NULL COLLATE NOCASE,
                sistema_operativo TEXT NOT NULL,
                version_sistema   TEXT,
                nombre_equipo     TEXT,
                dominio           TEXT,
                creado_en         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ultimo_acceso     TEXT, activo INTEGER NOT NULL DEFAULT 1,
                UNIQUE(nombre_usuario, sistema_operativo, nombre_equipo, dominio)
            );
INSERT INTO "usuarios_sistema" VALUES(1,'__default__','sistema','','','','2026-11-24 21:27:02',NULL,1);
CREATE TABLE venta_items (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER NOT NULL REFERENCES ventas(id),
                producto TEXT NOT NULL,
                precio   REAL NOT NULL,
                cantidad INTEGER NOT NULL,
                subtotal REAL NOT NULL
            );
CREATE TABLE ventas (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha    TEXT NOT NULL,
                hora     TEXT NOT NULL,
                total    REAL NOT NULL,
                recibido REAL NOT NULL,
                cambio   REAL NOT NULL
            , sesion_id INTEGER REFERENCES sesiones_sistema(id));
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('usuarios_sistema',1);
