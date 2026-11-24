-- Esquema de la v3, versión 1: las tablas de la v2 que la v3 sigue usando, con la misma estructura
-- que tiene la base de producción (tomada de ella el 2026-11-24, con las columnas que la v2 agregó
-- después con sus migraciones). Así la importación desde la v2 es casi uno a uno.
--
-- Fuera: `autorizaciones_codigos`, que guarda los códigos de autorización en texto plano (D20/D21:
-- en la v3 el código va como hash y las aperturas en `aperturas_caja`, versión 2).

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

CREATE TABLE ventas (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha    TEXT NOT NULL,
                    hora     TEXT NOT NULL,
                    total    REAL NOT NULL,
                    recibido REAL NOT NULL,
                    cambio   REAL NOT NULL
                , sesion_id INTEGER REFERENCES sesiones_sistema(id));

CREATE TABLE venta_items (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id INTEGER NOT NULL REFERENCES ventas(id),
                    producto TEXT NOT NULL,
                    precio   REAL NOT NULL,
                    cantidad INTEGER NOT NULL,
                    subtotal REAL NOT NULL
                );

CREATE TABLE eventos_especiales (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha    TEXT NOT NULL,
                    hora     TEXT NOT NULL,
                    evento   TEXT NOT NULL,
                    detalle  TEXT
                , sesion_id INTEGER REFERENCES sesiones_sistema(id));

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

CREATE TABLE botones (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_interno TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    etiqueta       TEXT NOT NULL,
                    archivo_accion TEXT NOT NULL,
                    orden          INTEGER NOT NULL DEFAULT 0,
                    activo         INTEGER NOT NULL DEFAULT 1,
                    creado_en      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

CREATE TABLE boton_visibilidad (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            boton_id   INTEGER NOT NULL REFERENCES botones(id) ON DELETE CASCADE,
            usuario_id INTEGER NOT NULL REFERENCES usuarios_sistema(id) ON DELETE CASCADE,
            UNIQUE(boton_id, usuario_id)
        );

-- Usuario plantilla de la v2: nunca inicia sesión; los botones que tenga otorgados se copian a los
-- usuarios nuevos en su primer ingreso (P1: botones configurables).
INSERT INTO usuarios_sistema (nombre_usuario, sistema_operativo, version_sistema, nombre_equipo, dominio)
VALUES ('__default__', 'sistema', '', '', '');
