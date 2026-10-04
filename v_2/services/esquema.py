"""Esquema de ventas.db: todas las tablas del POS y sus migraciones.

Vive aparte de los servicios para que cada uno (ventas, catalogo, codigos de
barras, usuarios) pueda crear la base sin depender de los demas. Es idempotente:
cada servicio la llama al construirse. Las tablas de botones las crea
BotonesService (son de administracion, no del punto de venta)."""

from __future__ import annotations

from services.base_datos import conectar, tabla_tiene_columnas
from services.identidad import USUARIO_PLANTILLA


def asegurar_esquema(db_path=None):
    with conectar(db_path) as con:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ventas (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha    TEXT NOT NULL,
                hora     TEXT NOT NULL,
                total    REAL NOT NULL,
                recibido REAL NOT NULL,
                cambio   REAL NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS eventos_especiales (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha    TEXT NOT NULL,
                hora     TEXT NOT NULL,
                evento   TEXT NOT NULL,
                detalle  TEXT
            )
            """
        )
        if tabla_tiene_columnas(cur, "autorizaciones_codigos", {"fecha", "hora"}):
            _migrar_autorizaciones_codigos(cur)
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS autorizaciones_codigos (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo    TEXT NOT NULL,
                    evento_id INTEGER REFERENCES eventos_especiales(id)
                )
                """
            )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS venta_items (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER NOT NULL REFERENCES ventas(id),
                producto TEXT NOT NULL,
                precio   REAL NOT NULL,
                cantidad INTEGER NOT NULL,
                subtotal REAL NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS catalogo_autocompletado (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                producto   TEXT NOT NULL UNIQUE COLLATE NOCASE,
                creado_en  TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS codigos_barras_registrados (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_barras  TEXT NOT NULL UNIQUE COLLATE NOCASE,
                producto_id    INTEGER NOT NULL REFERENCES catalogo_autocompletado(id),
                precio_venta   REAL NOT NULL,
                creado_en      TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios_sistema (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_usuario    TEXT NOT NULL COLLATE NOCASE,
                sistema_operativo TEXT NOT NULL,
                version_sistema   TEXT,
                nombre_equipo     TEXT,
                dominio           TEXT,
                creado_en         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ultimo_acceso     TEXT,
                UNIQUE(nombre_usuario, sistema_operativo, nombre_equipo, dominio)
            )
            """
        )
        if not tabla_tiene_columnas(
            cur,
            "usuarios_sistema",
            {"sistema_operativo", "version_sistema", "nombre_equipo", "dominio", "creado_en", "ultimo_acceso"},
        ):
            _migrar_usuarios_sistema(cur)
        # Despues de la migracion (que reconstruye la tabla) para que no la pierda.
        if not tabla_tiene_columnas(cur, "usuarios_sistema", {"activo"}):
            cur.execute("ALTER TABLE usuarios_sistema ADD COLUMN activo INTEGER NOT NULL DEFAULT 1")
        cur.execute(
            """
            INSERT OR IGNORE INTO usuarios_sistema
                (nombre_usuario, sistema_operativo, version_sistema, nombre_equipo, dominio)
            VALUES (?, 'sistema', '', '', '')
            """,
            (USUARIO_PLANTILLA,),
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sesiones_sistema (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id            INTEGER NOT NULL REFERENCES usuarios_sistema(id),
                inicio                TEXT NOT NULL,
                ultimo_latido         TEXT NOT NULL,
                salida_real           TEXT,
                cerrada_correctamente INTEGER NOT NULL DEFAULT 0,
                pid                   INTEGER,
                detalle               TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS impresiones_codigos_barras (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha         TEXT NOT NULL,
                hora          TEXT NOT NULL,
                codigo_barras TEXT NOT NULL,
                copias        INTEGER NOT NULL,
                horizontal    INTEGER NOT NULL DEFAULT 0,
                codificador   TEXT,
                sesion_id     INTEGER REFERENCES sesiones_sistema(id)
            )
            """
        )
        _asegurar_autoria(cur)
        con.commit()


def _asegurar_autoria(cur):
    # Quién hizo cada cosa queda explícito: la sesión del POS (y por ella el usuario y el
    # equipo) se guarda en cada fila. Antes se deducía cruzando la hora con
    # sesiones_sistema, y eso falla con sesiones encimadas o un POS abierto toda la noche.
    # Las filas viejas se quedan con sesion_id NULL: no se les inventa autor.
    for tabla in ("ventas", "eventos_especiales"):
        if not tabla_tiene_columnas(cur, tabla, {"sesion_id"}):
            cur.execute(f"ALTER TABLE {tabla} ADD COLUMN sesion_id INTEGER REFERENCES sesiones_sistema(id)")

    for tabla in ("catalogo_autocompletado", "codigos_barras_registrados"):
        if not tabla_tiene_columnas(cur, tabla, {"sesion_id"}):
            cur.execute(f"ALTER TABLE {tabla} ADD COLUMN sesion_id INTEGER REFERENCES sesiones_sistema(id)")
            # creado_en se llenaba con el CURRENT_TIMESTAMP de SQLite, que es UTC, mientras que
            # el resto de la base usa hora local; desde ahora los servicios la escriben en hora
            # local, y las filas viejas se convierten una sola vez, aquí (solo corre la vez
            # que se agrega sesion_id).
            cur.execute(f"UPDATE {tabla} SET creado_en = datetime(creado_en, 'localtime') WHERE creado_en IS NOT NULL")

    if not tabla_tiene_columnas(cur, "catalogo_autocompletado", {"actualizado_en"}):
        cur.execute("ALTER TABLE catalogo_autocompletado ADD COLUMN actualizado_en TEXT")
        cur.execute(
            "ALTER TABLE catalogo_autocompletado ADD COLUMN actualizado_sesion_id INTEGER REFERENCES sesiones_sistema(id)"
        )


def _migrar_autorizaciones_codigos(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS autorizaciones_codigos_nueva (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo    TEXT NOT NULL,
            evento_id INTEGER REFERENCES eventos_especiales(id)
        )
        """
    )
    cur.execute(
        "INSERT INTO autorizaciones_codigos_nueva (id, codigo, evento_id) SELECT id, codigo, evento_id FROM autorizaciones_codigos"
    )
    cur.execute("DROP TABLE autorizaciones_codigos")
    cur.execute("ALTER TABLE autorizaciones_codigos_nueva RENAME TO autorizaciones_codigos")


def _migrar_usuarios_sistema(cur):
    cur.execute("PRAGMA table_info(usuarios_sistema)")
    columnas_existentes = [fila[1] for fila in cur.fetchall()]
    if not columnas_existentes:
        return

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios_sistema_nueva (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_usuario    TEXT NOT NULL COLLATE NOCASE,
            sistema_operativo TEXT NOT NULL,
            version_sistema   TEXT,
            nombre_equipo     TEXT,
            dominio           TEXT,
            creado_en         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ultimo_acceso     TEXT,
            UNIQUE(nombre_usuario, sistema_operativo, nombre_equipo, dominio)
        )
        """
    )

    columnas_insert = ["id", "nombre_usuario"]
    valores_select = ["id", "nombre_usuario"]

    if "sistema_operativo" in columnas_existentes:
        columnas_insert.append("sistema_operativo")
        valores_select.append("COALESCE(sistema_operativo, 'desconocido')")
    else:
        columnas_insert.append("sistema_operativo")
        valores_select.append("'desconocido'")

    if "version_sistema" in columnas_existentes:
        columnas_insert.append("version_sistema")
        valores_select.append("COALESCE(version_sistema, '')")
    else:
        columnas_insert.append("version_sistema")
        valores_select.append("''")

    if "nombre_equipo" in columnas_existentes:
        columnas_insert.append("nombre_equipo")
        valores_select.append("COALESCE(nombre_equipo, '')")
    else:
        columnas_insert.append("nombre_equipo")
        valores_select.append("''")

    if "dominio" in columnas_existentes:
        columnas_insert.append("dominio")
        valores_select.append("COALESCE(dominio, '')")
    else:
        columnas_insert.append("dominio")
        valores_select.append("''")

    if "creado_en" in columnas_existentes:
        columnas_insert.append("creado_en")
        valores_select.append("creado_en")
    else:
        columnas_insert.append("creado_en")
        valores_select.append("CURRENT_TIMESTAMP")

    if "ultimo_acceso" in columnas_existentes:
        columnas_insert.append("ultimo_acceso")
        valores_select.append("ultimo_acceso")
    else:
        columnas_insert.append("ultimo_acceso")
        valores_select.append("NULL")

    cur.execute(
        f"INSERT INTO usuarios_sistema_nueva ({', '.join(columnas_insert)}) SELECT {', '.join(valores_select)} FROM usuarios_sistema"
    )
    cur.execute("DROP TABLE usuarios_sistema")
    cur.execute("ALTER TABLE usuarios_sistema_nueva RENAME TO usuarios_sistema")
