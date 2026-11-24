-- Esquema de la v3, versión 3: el cobro rápido sin ticket (D15). Se guarda la marca para saber qué
-- ventas no imprimieron ticket; en esas, recibido = total y cambio = 0, y el cajón se abre igual
-- (su apertura entra a `aperturas_caja` como "venta").
ALTER TABLE ventas ADD COLUMN sin_ticket INTEGER NOT NULL DEFAULT 0 CHECK (sin_ticket IN (0, 1));
