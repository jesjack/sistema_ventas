# Pendientes para la instancia que trabaja en la app del POS

- [ ] **Corrector ortográfico para el catálogo de productos.** Añadir un diccionario de corrección
  (o normalización) para los nombres del catálogo de autocompletado (`ui/catalogo_autocompletado.py`,
  tabla `catalogo_autocompletado` de `v_2/ventas.db`). El catálogo se actualiza constantemente y los
  nombres se escriben a mano, con errores como `blusa basica`, `mayon deportivo` o `bycker`; el
  usuario quiere una ayuda al agregar/editar productos que sugiera o aplique la forma correcta.
  Lo pidió el usuario el 2026-09-18. La instancia que trabaja en `camera_viewer` no lo hace a propósito
  (está enfocada en esa app). Al terminarlo, borra este punto.
