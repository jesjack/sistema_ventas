import time

from dialogs.cobro_uno import solicitar_monto_cliente
from services.ventas_service import VentasService
from hardware.ticket_printer import imprimir_ticket_venta

ventas_service = VentasService()


class TableManager:
    def __init__(self, uno_context=None, ventas_service_instance=None, cobro_provider=None):
        self.uno_context = uno_context
        self.ventas_service = ventas_service_instance or ventas_service
        self.cobro_provider = cobro_provider or (
            lambda total: solicitar_monto_cliente(total, self.uno_context)
        )

    def add_item_to_cart(self, input_table, cart_table):
        input_data = list(input_table[0])
        if not input_data:
            return False

        producto, precio, cantidad = input_data
        if not producto or not precio or not cantidad:
            print("Todos los campos deben estar completos para agregar al carrito.")
            return False

        for index, row in enumerate(cart_table):
            if row[0] == producto and row[1] == precio:
                cantidad_total = row[2] + cantidad
                cart_table[index] = (producto, precio, cantidad_total, precio * cantidad_total)
                break
        else:
            cart_table.append((producto, precio, cantidad, precio * cantidad))

        input_table.clear()
        input_table.append(["", "", 1])
        return True

    def sell_items(self, cart_table, ventas_table):
        if not cart_table:
            print("El carrito esta vacio. No hay nada que vender.")
            return "code"

        items_vendidos = list(cart_table)
        total = sum(float(item[3]) for item in items_vendidos)
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
            imprimir_ticket_venta(items_vendidos, total, recibido, cambio)
        except Exception as exc:
            print(f"No se pudo generar el ticket de venta: {exc}")
        cart_table.clear()
        return None

    def load_sales(self, ventas_table):
        ventas = self.ventas_service.obtener_ventas()
        for venta in ventas:
            hora, producto, precio, cantidad, subtotal = venta
            ventas_table.append((hora, producto, precio, cantidad, subtotal))

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
