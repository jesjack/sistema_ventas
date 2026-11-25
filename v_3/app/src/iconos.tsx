// Iconos de los botones de la caja, con las reglas de la iconografía de NexFluid (retícula de
// 24 px, trazo de 1.5 px, extremos redondos, currentColor). NexFluid trae un juego pequeño a
// propósito ("un icono entra cuando un componente lo necesita"); estos son de la caja.

const TRAZOS: Record<string, string[]> = {
  // Billete
  cobrar_carrito: ['M3 7a1 1 0 0 1 1-1h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z', 'M12 9.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5', 'M6.5 9.5v.01', 'M17.5 14.5v.01'],
  // Bote de basura
  limpiar_carrito: ['M4 7h16', 'M9 7V4.5h6V7', 'M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12', 'M10 11v6', 'M14 11v6'],
  // Cajón de dinero
  abrir_caja: ['M3 13h18v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', 'M5 13l1.5-7h11l1.5 7', 'M10 16.5h4', 'M9 9h6'],
  // Tijeras
  corte_de_caja: ['M6 3.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5', 'M6 15.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5', 'M8.2 7.2L20 18', 'M8.2 16.8L20 6'],
  // Lista con lápiz (el catálogo)
  autocompletado: ['M4 6h11', 'M4 11h8', 'M4 16h5', 'M13.5 20.5l.8-3.3 5.6-5.6a1.5 1.5 0 0 1 2.1 2.1l-5.6 5.6z'],
  // Código de barras
  ver_codigos_de_barras: ['M4 5v14', 'M7 5v14', 'M10.5 5v14', 'M13 5v14', 'M16.5 5v14', 'M20 5v14'],
  // Impresora
  imprimir_varios_codigos: ['M7 9V3.5h10V9', 'M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2', 'M7 14h10v6.5H7z'],
  imprimir_codigo_de_barras: ['M7 9V3.5h10V9', 'M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2', 'M7 14h10v6.5H7z'],
  // Cámara
  ver_camaras: ['M3 8.5a2 2 0 0 1 2-2h2.2L9 4h6l1.8 2.5H19a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', 'M12 9.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 1 0 0-7'],
  // Lista (ventas)
  ver_ventas: ['M8 6h12', 'M8 12h12', 'M8 18h12', 'M4 6v.01', 'M4 12v.01', 'M4 18v.01'],
  // Llave (códigos de caja)
  codigos_caja: ['M8 10.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 1 0 0-7', 'M11.5 14H21', 'M18 14v3', 'M15 14v2'],
  // Carrito
  carrito: ['M3 4h2.5l2.2 11h10.6l2-7.5H6.4', 'M9 19.5v.01', 'M17 19.5v.01'],
}

export function Icono({ nombre, tam = 18 }: { nombre: string; tam?: number }) {
  const trazos = TRAZOS[nombre] ?? ['M12 12v.01']
  return (
    <svg
      width={tam}
      height={tam}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {trazos.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}
