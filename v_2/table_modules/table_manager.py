import time

from table_modules.carrito import agregar_al_carrito, total_del_carrito


class TableManager:
    """Une las tablas de la hoja con los servicios: vender, cargar el historial y
    registrar eventos. Todo lo externo (base de datos, cobro, ticket) llega por el
    constructor, asi que importar este modulo no abre nada y se puede probar con
    dobles."""

    def __init__(self, ventas_service, cobro_provider, imprimir_ticket):
        self.ventas_service = ventas_service
        self.cobro_provider = cobro_provider  # total -> (recibido, cambio) | None si se cancela
        self.imprimir_ticket = imprimir_ticket  # (items, total, recibido, cambio)

    def add_item_to_cart(self, input_table, cart_table):
        return agregar_al_carrito(input_table, cart_table)

    def sell_items(self, cart_table, ventas_table):
        if not cart_table:
            print("El carrito esta vacio. No hay nada que vender.")
            return "code"

        items_vendidos = list(cart_table)
        total = total_del_carrito(items_vendidos)
        cobro = self.cobro_provider(total)
        if cobro is None:
            print("Venta cancelada por el usuario.")
            return None

        recibido, cambio = cobro
        for row in cart_table:
            hora = time.strftime("%H:%M:%S")
            producto, precio, cantidad, subtotal = row
            ventas_table.append((hora, producto, precio, cantidad, subtotal))

        self.ventas_service.registrar_venta(items_vendidos, recibido=recibido, cambio=cambio)
        try:
            self.imprimir_ticket(items_vendidos, total, recibido, cambio)
        except Exception as exc:
            print(f"No se pudo generar el ticket de venta: {exc}")
        cart_table.clear()
        return None

    def load_sales(self, ventas_table):
        ventas = self.ventas_service.obtener_ventas(desde_ultimo_corte=True)
        for venta in ventas:
            hora, producto, precio, cantidad, subtotal = venta
            ventas_table.append((hora, producto, precio, cantidad, subtotal))

    def cash_cut(self, ventas_table, cambio):
        """Corte de caja: lo registra y deja la tabla solo con el cambio que quedó en la caja."""
        corte_id = self.ventas_service.registrar_corte_de_caja(cambio)
        self.reload_sales(ventas_table)
        return corte_id

    def reload_sales(self, ventas_table):
        """Vuelve a llenar la tabla desde la base (tras un corte de caja, por ejemplo)."""
        ventas_table.clear()
        ventas_table.extend(self.ventas_service.obtener_ventas(desde_ultimo_corte=True))

    def registrar_evento_especial(self, ventas_table, evento, codigo=None, detalle=None):
        hora = time.strftime("%H:%M:%S")
        event_id = self.ventas_service.registrar_evento_especial(
            evento,
            detalle=detalle,
            hora=hora,
        )

        if codigo is not None:
            self.ventas_service.registrar_codigo_autorizacion(
                codigo,
                evento_id=event_id,
                detalle=detalle,
                hora=hora,
            )

        ventas_table.append((hora, evento, "", "", ""))
