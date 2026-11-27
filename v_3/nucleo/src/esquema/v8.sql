-- Esquema de la v3, versión 8: cómo se pagó (pedido el 2026-11-26). Los pagos con tarjeta van a la
-- cuenta de Mercado Pago del dueño, no a la caja: antes se anotaban con un precio negativo como
-- recordatorio. Una venta con tarjeta no abre el cajón y no cuenta en el efectivo de la caja.
ALTER TABLE ventas ADD COLUMN metodo_pago TEXT NOT NULL DEFAULT 'efectivo' CHECK (metodo_pago IN ('efectivo', 'tarjeta'));
