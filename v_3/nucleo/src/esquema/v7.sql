-- Esquema de la v3, versión 7: correcciones del catálogo que se aprenden cuando alguien corrige
-- una palabra a mano en el editor ("bycker" → "biker"). `incorrecta` va sin acentos y en
-- minúsculas, así coincide se escriba como se escriba. Ver `corrector.rs`.
CREATE TABLE correcciones_catalogo (
    incorrecta TEXT PRIMARY KEY,
    correcta   TEXT NOT NULL,
    creado_en  TEXT NOT NULL,
    sesion_id  INTEGER REFERENCES sesiones_sistema(id)
);
