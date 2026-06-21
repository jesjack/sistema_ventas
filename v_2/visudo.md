# Configuración de Sudo sin Contraseña para Scripts de Python (Librería Keyboard)

Este documento detalla los pasos necesarios en Linux para permitir que un script específico de Python que utiliza la librería `keyboard` se ejecute con privilegios de administrador (`sudo`) sin solicitar contraseña, manteniendo el sistema seguro.

---

## 1. Asegurar los Permisos del Script (Seguridad Crítica)
Antes de otorgar permisos en `sudoers`, debemos asegurar que **ningún otro usuario** pueda modificar o reemplazar el script ni la carpeta que lo contiene. Esto evita que terceros inyecten código malicioso que se ejecutaría como `root`.

Ejecuta los siguientes comandos para restringir el acceso:

```bash
# Cambia los permisos para que SOLO tu usuario pueda leer, escribir y ejecutar el script
chmod 700 /home/jesjack/sistema_ventas/v_2/tu_script.py

# Protege la carpeta contenedora para evitar que borren o reemplacen el archivo
chmod 755 /home/jesjack/sistema_ventas/v_2
```

Para verificar que los permisos se aplicaron correctamente:
```bash
ls -l /home/jesjack/sistema_ventas/v_2/tu_script.py
```
*La salida debe empezar por `-rwx------`, lo que confirma que solo tú tienes acceso completo.*

---

## 2. Configurar `sudoers` para Ejecución sin Contraseña

Para saltarte la solicitud de contraseña, debes agregar una regla de excepción en el archivo de configuración de `sudo`.

1. Abre el editor seguro de sudoers:
   ```bash
   sudo visudo
   ```

2. Ve al final del archivo y añade la siguiente línea exacta (reemplaza `tu_script.py` por el nombre real de tu archivo):
   ```text
   jesjack ALL=(ALL) NOPASSWD: /usr/bin/python3 /home/jesjack/sistema_ventas/v_2/tu_script.py
   ```

3. **Guardar y salir (Si usas el editor Nano por defecto):**
   * Presiona `Ctrl + O` y luego `Enter` para guardar.
   * Presiona `Ctrl + X` para salir.

---

## 3. Ejecución del Programa

A partir de este momento, puedes ejecutar tu script de automatización del teclado usando `sudo`. El sistema validará la ruta y **no te pedirá ninguna contraseña**:

```bash
sudo /usr/bin/python3 /home/jesjack/sistema_ventas/v_2/tu_script.py
```

---

## 📌 Notas y Recordatorios
* **Rutas Absolutas:** `visudo` requiere obligatoriamente rutas completas (ej. `/usr/bin/python3` en lugar de solo `python3`).
* **Modificaciones futuras:** Si cambias el script de carpeta o le cambias el nombre, deberás actualizar la ruta exacta dentro de `sudo visudo`, de lo contrario volverá a pedir contraseña.
