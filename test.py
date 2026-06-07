import sys
import qrcode
from PIL import Image

def generar_qr_archivo_fijo(texto_qr):
    # Nombre de archivo fijo que siempre se usará
    NOMBRE_ARCHIVO = "/tmp/qr_buffer.bin"

    # 1. Configurar y generar el código QR
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,  
        border=1,    
    )
    qr.add_data(texto_qr)
    qr.make(fit=True)
    
    # Convertir a modo "1" (monocromático puro)
    img = qr.make_image(fill_color="black", back_color="white").convert("1")
    ancho, alto = img.size
    ancho_bytes = (ancho + 7) // 8

    # 2. Procesar la imagen a bytes puros (sin comandos ESC/POS)
    datos_imagen = bytearray()
    for y in range(alto):
        for b in range(ancho_bytes):
            byte_actual = 0
            for bit in range(8):
                x = b * 8 + bit
                if x < ancho:
                    pixel = img.getpixel((x, y))
                    if pixel == 0:  # Si el píxel es negro, activamos el bit
                        byte_actual |= (1 << (7 - bit))
            datos_imagen.append(byte_actual)

    # 3. Guardar directamente en el archivo fijo en modo binario ("wb")
    # Nota: Esto sobrescribirá el archivo anterior si ya existe, lo cual es ideal
    with open(NOMBRE_ARCHIVO, "wb") as f:
        f.write(datos_imagen)

    sys.stdout.write(f"Archivo guardado: {NOMBRE_ARCHIVO}\n")

if __name__ == "__main__":
    url_final = sys.argv[1] if len(sys.argv) > 1 else "https://fb.com/share/1E14r1SK7f"
    generar_qr_archivo_fijo(url_final)
