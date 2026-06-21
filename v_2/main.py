import uno
from table_calc import create_table
from sheet_manager import SheetManager
import keyboard

if __name__ == "__main__":
    # Conectar a LibreOffice
    local_context = uno.getComponentContext()
    resolver = local_context.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local_context)
    context = resolver.resolve("uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
    desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
    documento = desktop.getCurrentComponent()
    hoja = documento.Sheets[0]
    
    manager = SheetManager(hoja, document=documento)
    manager.set_column_width(0, 600)
    manager.set_column_width(1, 7700)
    manager.set_column_width(2, 1600)
    manager.set_column_width(3, 600)
    manager.set_column_width(5, 600)

    manager.format_column_as_currency(2)
    manager.format_column_as_currency(4)

    input = create_table(hoja, 1, 1, ["PRODUCTO", "PRECIO", "C."])
    input.append(["", "", 1])
    input.header_color = 0x9B111E
    input.title = "INGRESE LOS DATOS"

    cart = create_table(hoja, 1, 5, ["PRODUCTO", "PRECIO", "C.", "SUBTOTAL"])
    cart.header_color = 0x1CA9C9
    cart.title = "CARRITO DE COMPRA"
    cart.show_total = True
    cart.total_label_span = 2
    cart.placeholder = "EL CARRITO ESTÁ VACÍO"

    keyboard.add_hotkey("enter", lambda: manager.add_row(input, cart))